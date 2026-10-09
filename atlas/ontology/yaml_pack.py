"""A legacy YAML pack, imported into the OWL layer as the axioms it states.

Packs were the library's first ontology format: a list of types with a parent, fields and
a disjointness list, and a list of relations with a domain, a range and characteristics.
Every one of those is an OWL 2 axiom or an annotation, so a pack is read by writing it
into the same RDF graph an ontology file is parsed into -- `rdfs:subClassOf`,
`owl:disjointWith`, `rdfs:domain`, `owl:TransitiveProperty`, `atlas:fields` -- and from
there it is the same ontology as any other, reasoned over by the same engines.

It is kept because consumers store packs and edit them structurally, and because a pack
is still the quickest way to write down a first vocabulary. It is not the format this
library ships its ontologies in any more: those are Turtle, under `ontologies/`, and they
say things a pack has no way to say -- defined classes, restrictions, property chains,
disjoint properties.

The rules a pack was held to are kept exactly, because consumers depend on them: a pack
is a mapping; a key its model does not declare is refused; a pack that declares prefixes
must give every term an IRI; a parent must name a type of the merged packs; a name
declared twice is refused. The version of a schema loaded from packs alone is still the
hash of the pack bytes, so a stored version does not move under a consumer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection

from atlas.model import FieldDef, PredicateDef, Schema, TypeDef
from atlas.ontology.vocabulary import ATLAS, OWL, RDF, RDFS, SKOS, local, local_field

KEYS = ("prefixes", "types", "predicates")
"""What a pack's loader reads. Anything else in the file -- a consumer's own extension --
is left alone, which is how a pack carries more than the library knows about."""


@dataclass
class Pack:
    """One pack, read and checked, with the IRI each of its terms will have."""

    path: Path
    prefixes: dict[str, str]
    types: list[TypeDef] = field(default_factory=list)
    predicates: list[PredicateDef] = field(default_factory=list)
    type_iris: dict[str, str] = field(default_factory=dict)
    predicate_iris: dict[str, str] = field(default_factory=dict)


def read(raw: bytes, path: Path) -> Pack:
    """Parse and check one pack; no names are resolved yet, because a parent may be elsewhere."""
    document = yaml.safe_load(raw) or {}
    if not isinstance(document, dict):
        raise ValueError(f"{path}: a pack must be a mapping")
    prefixes = {str(k): str(v) for k, v in (document.get("prefixes") or {}).items()}
    scope = Schema(version="", prefixes=prefixes)
    pack = Pack(path=path, prefixes=prefixes)
    for entry in document.get("types") or ():
        fields = tuple(_field(one, scope) for one in entry.get("fields") or ())
        type_def = TypeDef(**{**entry, "iri": _iri(entry, scope, path), "fields": fields})
        pack.types.append(type_def)
        pack.type_iris[type_def.name] = type_def.iri or local(type_def.name)
    for entry in document.get("predicates") or ():
        predicate = PredicateDef(**{**entry, "iri": _iri(entry, scope, path)})
        pack.predicates.append(predicate)
        pack.predicate_iris[predicate.name] = predicate.iri or local(predicate.name)
    return pack


def write(packs: list[Pack], graph: Graph, known_types: dict[str, str],
          known_predicates: dict[str, str], order: dict[str, float], offset: float) -> None:
    """Write the packs into the graph as OWL, resolving every name against the whole merge.

    `known_*` hold the names an ontology file already declared, so a pack may name a class
    of one as its parent. Names declared twice are refused here, before anything is written.
    """
    types = dict(known_types)
    predicates = dict(known_predicates)
    for pack in packs:
        for name, iri in pack.type_iris.items():
            if name in types:
                raise ValueError(f"duplicate name {name!r}")
            types[name] = iri
        for name, iri in pack.predicate_iris.items():
            if name in predicates:
                raise ValueError(f"duplicate name {name!r}")
            predicates[name] = iri
    for index, pack in enumerate(packs):
        for prefix, namespace in pack.prefixes.items():
            graph.bind(prefix, namespace, override=False)
        count = max(len(pack.types) + len(pack.predicates), 1)
        for position, type_def in enumerate(pack.types):
            order[pack.type_iris[type_def.name]] = offset + index + position / count
            _type(graph, type_def, pack, types)
        for position, predicate in enumerate(pack.predicates, start=len(pack.types)):
            order[pack.predicate_iris[predicate.name]] = offset + index + position / count
            _predicate(graph, predicate, pack, types, predicates)


def _type(graph: Graph, type_def: TypeDef, pack: Pack, types: dict[str, str]) -> None:
    subject = URIRef(pack.type_iris[type_def.name])
    graph.add((subject, RDF.type, OWL.Class))
    graph.add((subject, ATLAS.name, Literal(type_def.name)))
    if type_def.parent is not None:
        parent = _resolve(type_def.parent, types, pack)
        if parent is None:
            raise ValueError(f"type {type_def.name!r} has unknown parent {type_def.parent!r}")
        graph.add((subject, RDFS.subClassOf, URIRef(parent)))
    for other in type_def.disjoint_with:
        target = _resolve(other, types, pack) or local(other)
        graph.add((subject, OWL.disjointWith, URIRef(target)))
    if type_def.description:
        graph.add((subject, SKOS.definition, Literal(type_def.description)))
    listed = []
    for one in type_def.fields:
        prop = URIRef(one.iri or local_field(one.name, one.datatype))
        graph.add((prop, RDF.type, OWL.DatatypeProperty))
        graph.add((prop, ATLAS.name, Literal(one.name)))
        graph.add((prop, ATLAS.datatype, Literal(one.datatype)))
        listed.append(prop)
    if listed:
        head = BNode()
        Collection(graph, head, listed)
        graph.add((subject, ATLAS.fields, head))
    if type_def.label_field:
        target = next((f for f in type_def.fields if f.name == type_def.label_field), None)
        prop = (URIRef(target.iri or local_field(target.name, target.datatype)) if target
                else Literal(type_def.label_field))
        graph.add((subject, ATLAS.labelField, prop))
    if type_def.mappings:
        head = BNode()
        Collection(graph, head, [Literal(one) for one in type_def.mappings])
        graph.add((subject, ATLAS.mappings, head))


def _predicate(graph: Graph, predicate: PredicateDef, pack: Pack, types: dict[str, str],
               predicates: dict[str, str]) -> None:
    subject = URIRef(pack.predicate_iris[predicate.name])
    graph.add((subject, RDF.type, OWL.ObjectProperty))
    graph.add((subject, ATLAS.name, Literal(predicate.name)))
    for which, term in ((RDFS.domain, predicate.domain), (RDFS.range, predicate.range)):
        if term and term != "owl:Thing":
            target = _resolve(term, types, pack) or local(term)
            graph.add((subject, which, URIRef(target)))
    kinds = {"transitive": OWL.TransitiveProperty, "symmetric": OWL.SymmetricProperty,
             "asymmetric": OWL.AsymmetricProperty, "reflexive": OWL.ReflexiveProperty,
             "irreflexive": OWL.IrreflexiveProperty, "functional": OWL.FunctionalProperty,
             "inverse-functional": OWL.InverseFunctionalProperty}
    for named in predicate.characteristics:
        if named in kinds:
            graph.add((subject, RDF.type, kinds[named]))
        else:
            # Not an OWL characteristic. Kept as what the pack said, so the formal gate
            # can refuse it by name instead of the loader dropping it without a word.
            graph.add((subject, ATLAS.characteristic, Literal(named)))
    if predicate.inverse_of:
        target = (_resolve(predicate.inverse_of, predicates, pack)
                  or local(predicate.inverse_of))
        graph.add((subject, OWL.inverseOf, URIRef(target)))
    for parent in predicate.parents:
        target = _resolve(parent, predicates, pack) or local(parent)
        graph.add((subject, RDFS.subPropertyOf, URIRef(target)))
    if predicate.description:
        graph.add((subject, SKOS.definition, Literal(predicate.description)))
    if predicate.mappings:
        head = BNode()
        Collection(graph, head, [Literal(one) for one in predicate.mappings])
        graph.add((subject, ATLAS.mappings, head))


def _resolve(term: str, known: dict[str, str], pack: Pack) -> str | None:
    """The IRI of a name, or of a CURIE or IRI a pack wrote in place of one."""
    if term in known:
        return known[term]
    expanded = Schema(version="", prefixes=pack.prefixes).expand(term)
    return next((iri for iri in known.values() if iri == expanded), None)


def _field(entry: dict | str, scope: Schema) -> FieldDef:
    """A field is a mapping, or bare name shorthand for one that declares nothing else."""
    entry = {"name": entry} if isinstance(entry, str) else entry
    iri = entry.get("iri")
    return FieldDef(**{**entry, "iri": scope.expand(iri) if iri else None})


def _iri(entry: dict, scope: Schema, path: Path) -> str | None:
    iri = entry.get("iri")
    if iri is None and scope.prefixes:
        raise ValueError(f"{path}: term {entry.get('name')!r} declares no iri")
    return scope.expand(iri) if iri else None


__all__ = ["KEYS", "Pack", "read", "write"]
