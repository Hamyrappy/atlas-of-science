"""Pooling what the ontology has no word for, and the gate a pooled word has to pass.

An extractor working against a fixed profile throws away whatever fits none of it. On
a corpus the profile was not written for, that is most of what is interesting, and the
honest response is not to widen the profile until it stops meaning anything -- it is to
keep the refusals, watch which of them keep coming back, and promote one only when
there is a case for it.

`induce` is the pool. Statements of a type the schema does not know are grouped by what
their labels have in common, and each group accumulates: the surface forms it covers,
the quotes behind it, the **independent source families** it was seen in, and how many
rounds it has survived. The registry is written beside the store, so "two rounds" means
two runs and not two segments of one paper.

`promote` is the gate. A candidate becomes a proposed type when it has support in
enough independent families, has been stable across rounds, has a definition that
distinguishes it, and is not a word the loaded schema already has. It never becomes a
class: it becomes a **proposal**, written out as an OWL module -- `proposal.ttl`, importing
the ontology the run was under -- for somebody to read. Nothing in this library lets a model
edit the ontology a corpus is being marked up against, and this module is where that would
have been convenient.

**A proposal is reasoned over before anybody reads it.** It is loaded with the run's
ontology exactly as a configuration would load it -- parsed, merged, classified by the EL
engine, held to the run's profile -- and whatever that finds is returned in
`proposal_problems`: a name the ontology already gives to something else, a parent that
makes the new class empty, an axiom outside the profile. A reviewer is handed a module
that is known to load, or told why it does not.

Three decisions are worth naming, because each one is a way induction usually goes
wrong.

**Support counts families, not mentions.** Ten mentions in one paper are one paper. A
family is a source id by default, or the value of a `Source.meta` key -- a venue, a
group, a registry -- when the corpus knows something better. A model asked twice is not
two families either, which is why nothing here counts extractions.

**A word the schema already has is a reuse, not a discovery.** The closest existing
term is found and reported on every candidate, promoted or not, so "we invented a class
for something OBI already had" is visible rather than discovered later.

**A refusal carries its reason.** `refused` is a list of candidates with the gate they
failed, because a pool that only reports its successes cannot be tuned.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import Field
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection

from atlas.model import Frozen, Schema, Source
from atlas.ontology.vocabulary import ATLAS, HOME, LOCAL, OWL, RDF, RDFS, SKOS
from atlas.steps import State, register
from atlas.text import normalise, tokenise

REGISTRY = "candidates.json"
PROPOSAL = "proposal.ttl"
PROPOSED = f"{LOCAL}proposed"
"""Where a proposed class is put until a reviewer mints it an identity of its own."""
FIELDS = f"{HOME}fields"


class Candidate(Frozen):
    """One word the schema has no room for, and everything known about whether it deserves one."""

    term: str = Field(description="Normalised key the surface forms were grouped under")
    label: str = Field(description="The surface form shown to a reader")
    variants: tuple[str, ...] = ()
    families: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    definition: str = ""
    nearest: str = Field(default="", description="Closest term the loaded schema already has")
    similarity: float = 0.0
    rounds: int = 1

    @property
    def support(self) -> int:
        """How many independent source families offered it; the number the gate reads."""
        return len(self.families)


class Refusal(Frozen):
    """A candidate the gate turned down, with the reason, so the gate can be tuned."""

    candidate: Candidate
    reason: str


class InduceOptions(Frozen):
    """How labels are grouped, what counts as an independent family, where the pool lives."""

    similarity: float = Field(0.6, ge=0.0, le=1.0)
    family_field: str = Field(
        default="", description="`Source.meta` key naming the family; empty means the source id"
    )
    registry: str = Field(REGISTRY, pattern=r"^[^/\\]+$")
    examples: int = Field(3, ge=1)


@register("induce", requires=("statements", "schema", "sources"), produces=("candidates",),
          options=InduceOptions)
def induce(state: State, options: InduceOptions) -> State:
    """Pool the statements the schema has no type for, and merge the pool with earlier rounds."""
    schema: Schema = state["schema"]
    families = _families(state["sources"], options.family_field)
    groups: dict[str, dict] = {}
    for statement in state["statements"]:
        if schema.find_type(statement.type) is not None:
            continue
        key = _group(groups, statement.type, options.similarity)
        group = groups.setdefault(key, {"labels": [], "families": [], "examples": []})
        _add(group["labels"], statement.type)
        _add(group["families"], families.get(statement.source_id, statement.source_id))
        _add(group["examples"], statement.quote)
    found = tuple(
        _candidate(key, group, schema, options.examples) for key, group in sorted(groups.items())
    )
    store = state.get("store")
    path = store.artifact(options.registry) if store is not None else None
    return {"candidates": _merge(found, path)}


class PromoteOptions(Frozen):
    """The gate: how much support, how much stability, and when a word is somebody else's.

    `min_rounds` is why the registry exists. A candidate that appeared once, in three
    papers of one batch, is a batch; one that comes back in the next round is a word
    the corpus uses. `reuse` is the similarity above which the closest existing term is
    treated as the right answer, so the proposal says "use this" rather than minting a
    second name for it.
    """

    min_support: int = Field(3, ge=1)
    min_rounds: int = Field(2, ge=1)
    reuse: float = Field(0.75, ge=0.0, le=1.0)
    require_definition: bool = True
    parent: str = Field(default="", description="Class a proposed one is placed under, if any")
    out: str = Field(PROPOSAL, pattern=r"^[^/\\]+$")


@register("promote", requires=("candidates", "schema"),
          produces=("promoted", "refused", "proposal", "proposal_problems"),
          options=PromoteOptions)
def promote(state: State, options: PromoteOptions) -> State:
    """Judge every candidate, write the ones that pass as an OWL module, and load it to check."""
    schema: Schema = state["schema"]
    promoted: list[Candidate] = []
    refused: list[Refusal] = []
    for candidate in state["candidates"]:
        reason = _refuse(candidate, options)
        (refused.append(Refusal(candidate=candidate, reason=reason)) if reason
         else promoted.append(candidate))
    proposal = module(promoted, schema, options.parent)
    problems = check(proposal, schema, promoted) if proposal else ()
    store = state.get("store")
    path = store.artifact(options.out) if store is not None else None
    if path is not None and promoted:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(proposal, encoding="utf-8")
    return {"promoted": tuple(promoted), "refused": tuple(refused), "proposal": proposal,
            "proposal_problems": problems}


def module(candidates: Iterable[Candidate], schema: Schema, parent: str = "") -> str:
    """The promoted candidates as an OWL module in Turtle, importing the run's ontology.

    Each class gets a placeholder identity under `urn:atlas:local:proposed#`, never one in a
    namespace somebody publishes: deciding the identity -- minting one, or finding that an
    existing vocabulary already has the term -- is the review, and a file that guessed it
    would have made the review look finished. What the gate knew goes in an editorial note.
    """
    candidates = list(candidates)
    if not candidates:
        return ""
    g = Graph(bind_namespaces="core")
    for prefix, namespace in (("proposed", f"{PROPOSED}#"), ("field", f"{FIELDS}#"),
                              ("atlas", str(ATLAS)), ("skos", str(SKOS))):
        g.bind(prefix, namespace)
    ontology = URIRef(PROPOSED)
    g.add((ontology, RDF.type, OWL.Ontology))
    for imported in (schema.iri, FIELDS):
        if imported:
            g.add((ontology, OWL.imports, URIRef(imported)))
    above = schema.find_type(parent) if parent else None
    for candidate in candidates:
        iri = URIRef(f"{PROPOSED}#{_local(candidate.label)}")
        g.add((iri, RDF.type, OWL.Class))
        g.add((iri, ATLAS.name, Literal(candidate.label)))
        if above is not None:
            g.add((iri, RDFS.subClassOf, URIRef(above.iri or f"{LOCAL}{above.name}")))
        g.add((iri, SKOS.definition, Literal(
            candidate.definition or f"Proposed from {candidate.support} sources.")))
        g.add((iri, SKOS.editorialNote, Literal(_note(candidate))))
        fields = [URIRef(f"{FIELDS}#name"), URIRef(f"{FIELDS}#definition")]
        listed = BNode()
        Collection(g, listed, fields)
        g.add((iri, ATLAS.fields, listed))
        g.add((iri, ATLAS.labelField, fields[0]))
    header = (
        "# Proposed by `promote`, from candidates that passed the gate. Not an ontology yet:\n"
        "# no identities have been minted, and nothing here has been read by a person.\n"
        "# Reviewing it means deciding, for each class, whether an existing vocabulary\n"
        "# already has the term -- the editorial note names the nearest one -- and then\n"
        "# minting an IRI in a namespace you publish for each class that stays.\n"
    )
    return header + g.serialize(format="turtle")


def check(proposal: str, schema: Schema, candidates: Iterable[Candidate] = ()) -> tuple[str, ...]:
    """What goes wrong when the proposal is loaded with the run's ontology, as a run would.

    The run's ontology is written back out (`to_turtle`) rather than re-read from disk, so
    the proposal is checked against exactly the axioms the run reasoned with, and under
    the profile the run named.
    """
    from atlas.ontology import load_text
    from atlas.ontology.rdf import to_turtle

    try:
        merged = load_text(to_turtle(schema), proposal, profile=schema.profile)
    except ValueError as failure:
        return (str(failure),)
    problems = [f"{one.label}: the proposal leaves it with no possible member"
                for one in candidates if one.label in merged.unsatisfiable]
    problems += [f"{one.label}: the proposal does not load as a class"
                 for one in candidates if merged.find_type(one.label) is None]
    return tuple(problems)


def _local(label: str) -> str:
    """A label as the local part of an IRI: its words, capitalised and run together."""
    return "".join(word[:1].upper() + word[1:] for word in tokenise(label)) or "Unnamed"


def _note(candidate: Candidate) -> str:
    families = ", ".join(candidate.families)
    note = (f"Proposed from {candidate.support} independent source families ({families}) "
            f"over {candidate.rounds} round(s).")
    if candidate.nearest:
        note += (f" Closest existing term: {candidate.nearest} "
                 f"({candidate.similarity:.2f} overlap).")
    return note


def similarity(one: str, other: str) -> float:
    """How much two labels have in common, as the overlap of their terms.

    Jaccard over folded tokens: crude, symmetric, and it does not pretend to understand
    either word. Grouping and reuse both read it, and both report the number they used,
    so a threshold that is wrong for a corpus is visible rather than baked in.
    """
    left, right = set(tokenise(one)), set(tokenise(other))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _refuse(candidate: Candidate, options: PromoteOptions) -> str:
    """Why the gate turns this candidate down, or an empty string if it does not."""
    if candidate.support < options.min_support:
        return (f"support {candidate.support} in independent families, "
                f"below {options.min_support}")
    if candidate.rounds < options.min_rounds:
        return f"seen in {candidate.rounds} round(s), below {options.min_rounds}"
    # Reuse is checked before the definition, because it is the more useful answer: a
    # candidate that is the term the schema already has does not need to be defined, it
    # needs to be dropped, and refusing it for a missing definition would send somebody
    # to write one.
    if candidate.similarity >= options.reuse:
        return f"reuse {candidate.nearest!r} instead ({candidate.similarity:.2f} overlap)"
    if options.require_definition and not candidate.definition.strip():
        return "no definition distinguishing it from what the schema already has"
    return ""


def _candidate(key: str, group: dict, schema: Schema, examples: int) -> Candidate:
    """One pooled group, with the closest term the schema already has attached to it."""
    label = min(group["labels"], key=lambda one: (len(one), one))
    nearest, score = _nearest(label, schema)
    return Candidate(
        term=key,
        label=label,
        variants=tuple(sorted(group["labels"])),
        families=tuple(sorted(group["families"])),
        examples=tuple(group["examples"][:examples]),
        nearest=nearest,
        similarity=score,
    )


def _nearest(label: str, schema: Schema) -> tuple[str, float]:
    """The term of the loaded schema closest to a label, and how close it is."""
    scored = [
        (type_def.name, similarity(label, type_def.name)) for type_def in schema.types
    ]
    return max(scored, key=lambda pair: pair[1], default=("", 0.0))


def _group(groups: Mapping[str, dict], label: str, threshold: float) -> str:
    """The key a label joins: the closest existing group above the threshold, or its own.

    Greedy and order-dependent, which is the honest cost of not running a clustering
    algorithm over three words. The representative of a group is the first label it saw,
    so the grouping of one round is reproducible; across rounds the registry keys it.
    """
    joined, best = normalise(label), threshold
    for key, group in groups.items():
        score = similarity(label, group["labels"][0])
        if score >= best:
            joined, best = key, score
    return joined


def _add(items: list[str], value: str) -> None:
    """Append unless it is already there, keeping the order things were first seen in."""
    if value and value not in items:
        items.append(value)


def _families(sources: Iterable[Source], field: str) -> dict[str, str]:
    """Which family each source belongs to: a `meta` value if the corpus knows one, else itself."""
    return {
        source.id: (source.meta.get(field) or source.id) if field else source.id
        for source in sources
    }


def _merge(found: tuple[Candidate, ...], path: Path | None) -> tuple[Candidate, ...]:
    """Fold this round into the pool on disk, and write the pool back.

    Stability is the point: a candidate seen before keeps its rounds and gains one, and
    the families it was seen in accumulate across runs rather than being recounted from
    whatever happened to be in this batch. A store with nowhere to keep a file gets one
    round per run, which is stated here rather than discovered when nothing promotes.
    """
    held: dict[str, dict] = {}
    if path is not None and path.exists():
        try:
            held = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            held = {}  # A truncated registry is an empty pool, not a failed run.
    merged: list[Candidate] = []
    for candidate in found:
        before = held.get(candidate.term, {})
        families = tuple(sorted(set(candidate.families) | set(before.get("families", ()))))
        merged.append(candidate.model_copy(update={
            "families": families,
            "rounds": int(before.get("rounds", 0)) + 1,
            "definition": candidate.definition or before.get("definition", ""),
        }))
    held |= {
        one.term: {"families": list(one.families), "rounds": one.rounds,
                   "definition": one.definition, "label": one.label}
        for one in merged
    }
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(held, ensure_ascii=False, indent=2), encoding="utf-8")
    return tuple(merged)
