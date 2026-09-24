"""Reading ontologies and merging them into one `Schema`, reasoned over once on the way in.

The core names no vocabulary: `load()` with nothing to load is an empty schema, and every
type a corpus uses arrives from an ontology. The ones under `ontologies/` ship with the
library as OWL 2 in Turtle and are found through `builtin` whether the library is a
checkout or a wheel. This module is the only one that touches the filesystem; what the
terms mean is `atlas.model.schema` and `atlas.model.owl`, and what follows from them is
`atlas.reason`.

What happens to the files named, in order:

1. **Each is read in the format its suffix names** -- Turtle, RDF/XML, JSON-LD,
   N-Triples, or a legacy YAML pack -- and an `owl:imports` of one of this library's
   ontologies is followed, beside the importing file first and then among the shipped
   ones. An import from anywhere else is recorded in `Schema.imports` and not fetched:
   nothing here reaches the network.
2. **They become one RDF graph**, and every IRI in it is given one name. That is what
   lets a class declared in one file be the parent of a class in another.
3. **The graph is read into axioms and a vocabulary** (`atlas.ontology.rdf`), and the
   axioms are **classified** by the OWL 2 EL engine, which is what `Schema.is_a`
   answers from.
4. **The profile is enforced.** A configuration that names one gets an ontology inside
   it, or a `ValueError` naming the axioms that are not.

The version is the hash of the bytes read -- ontologies in load order, then shapes -- so
an object records the exact ontology it was written under and an edit to any file moves
it. A schema loaded from legacy packs alone hashes exactly as it always did.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, URIRef

from atlas.model import Schema
from atlas.ontology import yaml_pack
from atlas.ontology.rdf import Reader, declaration_order, to_graph, to_turtle
from atlas.ontology.vocabulary import HOME, OWL, PROFILES, RDF
from atlas.reason.el import classify
from atlas.reason.profile import explain

SHIPPED = (
    Path(__file__).parents[1] / "ontologies",
    Path(__file__).parents[2] / "ontologies",
)
"""Where the ontologies that travel with the library are: inside the installed package,
and beside it in a checkout. A consumer starting from one of them should not have to know
which of the two it is running from."""

SHAPES = "shapes"
"""The subdirectory of an ontology directory that holds SHACL shapes."""

SUFFIXES = {
    ".ttl": "turtle", ".owl": "xml", ".rdf": "xml", ".xml": "xml", ".jsonld": "json-ld",
    ".nt": "nt", ".n3": "n3", ".yaml": "yaml", ".yml": "yaml",
}
"""What a file is read as, by its suffix. `.owl` is RDF/XML, which is what Protégé writes
by default; save as Turtle to keep an ontology diffable."""

LOOKED_FOR = (".ttl", ".owl", ".yaml")


@dataclass(frozen=True)
class Document:
    """One ontology held as content: what it is called, its bytes, and how to read them."""

    name: str
    content: bytes
    format: str

    @classmethod
    def of(cls, path: Path) -> Document:
        form = SUFFIXES.get(path.suffix.lower())
        if form is None:
            raise ValueError(f"{path}: no reader for {path.suffix!r}; "
                             f"the readers are {', '.join(sorted(SUFFIXES))}")
        return cls(name=str(path), content=path.read_bytes(), format=form)

    @classmethod
    def text(cls, content: bytes | str, name: str = "ontology") -> Document:
        """Content with no file behind it, its format told from how it begins."""
        raw = content.encode("utf-8") if isinstance(content, str) else content
        # Comments are skipped first: Turtle and YAML both start them with `#`, and an
        # ontology file with a long header would otherwise be read as a pack.
        first = next((line.strip().lower() for line in raw.splitlines()
                      if line.strip() and not line.lstrip().startswith(b"#")), b"")
        if first.startswith((b"@prefix", b"@base", b"prefix ", b"base ")) or (
            first.startswith(b"<") and not first.startswith((b"<?xml", b"<rdf:rdf"))
        ):
            form = "turtle"
        elif first.startswith((b"<?xml", b"<rdf:rdf")):
            form = "xml"
        elif first.startswith((b"{", b"[")):
            form = "json-ld"
        else:
            form = "yaml"
        return cls(name=name, content=raw, format=form)


def builtin(name: str) -> Path:
    """The path of an ontology shipped with the library, named without its suffix."""
    for root in SHIPPED:
        for suffix in LOOKED_FOR:
            path = root / f"{name}{suffix}"
            if path.is_file():
                return path
    raise FileNotFoundError(f"no ontology {name!r} ships with the library")


def shape(name: str) -> Path:
    """The path of a SHACL shapes file shipped with the library, named without its suffix."""
    for root in SHIPPED:
        path = root / SHAPES / f"{name}.ttl"
        if path.is_file():
            return path
    raise FileNotFoundError(f"no shapes {name!r} ship with the library")


def resolve(spec: Path | str, base: Path | None = None) -> Path:
    """Where the ontology a configuration named is.

    Beside the file that named it, then under the working directory, then among the
    ontologies shipped with the library -- so several configurations in a subdirectory
    can share one ontology at the root of a corpus without writing `../` into every one
    of them, and `schema: science_core` needs no path at all.
    """
    spec = Path(spec)
    looked = [base / spec] if base is not None and not spec.is_absolute() else []
    looked.append(spec)
    for candidate in looked:
        if candidate.is_file():
            return candidate
    if spec.parent == Path("."):
        return builtin(spec.stem if spec.suffix in SUFFIXES else spec.name)
    raise FileNotFoundError(f"no ontology at {' or '.join(str(c) for c in looked)}")


def load(
    *specs: Path | str,
    base: Path | None = None,
    profile: str = "",
    shapes: Iterable[Path | str] = (),
) -> Schema:
    """Merge the ontologies these specs name, in order, into one versioned, classified schema.

    Each spec is resolved by `resolve` against `base`, which is the directory of the
    configuration that named it. `shapes` name SHACL files, resolved the same way and
    then among the shipped shapes.
    """
    documents: list[Document] = []
    unresolved: list[str] = []
    seen: set[Path] = set()
    for spec in specs:
        _gather(resolve(spec, base), documents, unresolved, seen)
    shape_documents = [Document.of(_resolve_shape(one, base)) for one in shapes]
    return build(documents, profile=profile, shapes=shape_documents, unresolved=unresolved)


def load_text(*contents: bytes | str | Document, profile: str = "",
              shapes: Iterable[bytes | str] = ()) -> Schema:
    """The same as `load`, for ontologies held as content rather than as files.

    For a consumer that keeps its ontologies in a database: the schema, the version hash
    and every check are exactly what `load` would give for the same bytes on disk.
    Imports of this library's own ontologies are resolved among the shipped ones.
    """
    documents: list[Document] = []
    unresolved: list[str] = []
    seen: set[Path] = set()
    for index, one in enumerate(contents):
        document = one if isinstance(one, Document) else Document.text(one, f"content-{index}")
        for iri in _imports_of(document):
            _import(iri, None, documents, unresolved, seen)
        documents.append(document)
    return build(documents, profile=profile,
                 shapes=[Document.text(one, "shapes") for one in shapes],
                 unresolved=unresolved)


def build(
    documents: list[Document],
    *,
    profile: str = "",
    shapes: Iterable[Document] = (),
    unresolved: Iterable[str] = (),
) -> Schema:
    """One schema from documents already read, which is what both loaders come down to."""
    if profile and profile not in PROFILES:
        raise ValueError(f"no profile {profile!r}; the profiles are {', '.join(PROFILES)}")
    shapes = list(shapes)
    raw = b"".join(one.content for one in documents) + b"".join(one.content for one in shapes)
    graph = Graph(bind_namespaces="core")
    order: dict[str, float] = {}
    prefixes: dict[str, str] = {}
    packs: list[yaml_pack.Pack] = []
    named = ""
    for index, document in enumerate(documents):
        if document.format == "yaml":
            pack = yaml_pack.read(document.content, Path(document.name))
            packs.append(pack)
            prefixes |= pack.prefixes
            continue
        parsed = Graph(bind_namespaces="core")
        try:
            parsed.parse(data=document.content, format=document.format)
        except Exception as failure:  # rdflib raises a dozen kinds; the name says which file
            raise ValueError(f"{document.name}: not readable as {document.format}: "
                             f"{failure}") from failure
        text = document.content.decode("utf-8", errors="replace")
        order |= declaration_order(text, parsed, float(index))
        for prefix, namespace in parsed.namespaces():
            if prefix and prefix not in ("owl", "rdf", "rdfs", "xsd", "xml"):
                prefixes.setdefault(prefix, str(namespace))
                graph.bind(prefix, namespace, override=False)
        for triple in parsed:
            graph.add(triple)
        # The schema is named after the ontology loaded last: imports are read before
        # the file that imports them, so that is the one the configuration named.
        named = next((str(s) for s in parsed.subjects(RDF.type, OWL.Ontology)
                      if isinstance(s, URIRef)), named)
    if packs:
        known = Reader(graph)
        yaml_pack.write(
            packs, graph,
            {name: str(iri) for iri, name in known.class_names.items()
             if iri in known.declared_classes},
            {name: str(iri) for iri, name in known.property_names.items()
             if iri in known.declared_properties},
            order, float(len(documents)),
        )
    projection = Reader(graph, order).projection()
    names = [one.name for one in projection.types]
    classified = classify(projection.axioms, names)
    schema = Schema(
        version=hashlib.sha256(raw).hexdigest()[:12],
        iri=named or projection.iri,
        prefixes=prefixes,
        types=tuple(projection.types),
        predicates=tuple(projection.predicates),
        axioms=tuple(projection.axioms),
        hierarchy={name: found for name, found in classified.hierarchy().items()
                   if name in names and found},
        unsatisfiable=tuple(sorted(one for one in classified.unsatisfiable if one in names)),
        profile=profile,
        shapes="\n".join(one.content.decode("utf-8") for one in shapes),
        imports=tuple(dict.fromkeys(unresolved)),
        unread=tuple(projection.unread),
    )
    if profile:
        problem = explain(schema.every_axiom(), profile)
        if problem:
            raise ValueError(f"the ontology is not within the profile the configuration "
                             f"names: {problem}")
    return schema


def _gather(path: Path, documents: list[Document], unresolved: list[str],
            seen: set[Path]) -> None:
    """One file and, before it, every ontology of this library it imports."""
    path = path.resolve()
    if path in seen:
        return
    seen.add(path)
    document = Document.of(path)
    for iri in _imports_of(document):
        _import(iri, path.parent, documents, unresolved, seen)
    documents.append(document)


def _import(iri: str, beside: Path | None, documents: list[Document], unresolved: list[str],
            seen: set[Path]) -> None:
    if not iri.startswith(HOME):
        unresolved.append(iri)
        return
    name = iri[len(HOME):].strip("/").split("/")[0]
    candidates = [beside / f"{name}{suffix}" for suffix in LOOKED_FOR] if beside else []
    found = next((one for one in candidates if one.is_file()), None)
    if found is None:
        try:
            found = builtin(name)
        except FileNotFoundError:
            unresolved.append(iri)
            return
    _gather(found, documents, unresolved, seen)


def _imports_of(document: Document) -> list[str]:
    if document.format == "yaml":
        return []
    parsed = Graph(bind_namespaces="core")
    try:
        parsed.parse(data=document.content, format=document.format)
    except Exception:  # the real parse reports it, with the file's name
        return []
    return sorted(str(one) for one in parsed.objects(None, OWL.imports))


def _resolve_shape(spec: Path | str, base: Path | None) -> Path:
    spec = Path(spec)
    for candidate in ([base / spec] if base is not None else []) + [spec]:
        if candidate.is_file():
            return candidate
    return shape(spec.stem if spec.suffix else spec.name)


__all__ = [
    "SHIPPED",
    "Document",
    "build",
    "builtin",
    "load",
    "load_text",
    "resolve",
    "shape",
    "to_graph",
    "to_turtle",
]
