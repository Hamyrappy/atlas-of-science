"""Pooling what the pack has no word for, and the gate a pooled word has to pass.

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
type: it becomes a **proposal**, written out as a pack fragment for somebody to read.
Nothing in this library lets a model edit the ontology a corpus is being marked up
against, and this module is where that would have been convenient.

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

import yaml
from pydantic import Field

from atlas.model import Frozen, Schema, Source
from atlas.steps import State, register
from atlas.text import normalise, tokenise

REGISTRY = "candidates.json"
PROPOSAL = "proposal.yaml"


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
    parent: str = Field(default="", description="Type a proposed one is placed under, if any")
    out: str = Field(PROPOSAL, pattern=r"^[^/\\]+$")


@register("promote", requires=("candidates", "schema"),
          produces=("promoted", "refused", "proposal"), options=PromoteOptions)
def promote(state: State, options: PromoteOptions) -> State:
    """Judge every candidate against the gate, and write the ones that pass out as a proposal."""
    promoted: list[Candidate] = []
    refused: list[Refusal] = []
    for candidate in state["candidates"]:
        reason = _refuse(candidate, options)
        (refused.append(Refusal(candidate=candidate, reason=reason)) if reason
         else promoted.append(candidate))
    proposal = pack(promoted, options.parent)
    store = state.get("store")
    path = store.artifact(options.out) if store is not None else None
    if path is not None and promoted:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(proposal, encoding="utf-8")
    return {"promoted": tuple(promoted), "refused": tuple(refused), "proposal": proposal}


def pack(candidates: Iterable[Candidate], parent: str = "") -> str:
    """The promoted candidates as a pack fragment, for a person to read before merging it.

    A fragment and not a pack: no prefixes, so the loader does not demand an IRI for a
    term nobody has minted one for yet. Deciding the identity is the review, and a file
    that guessed it would have made the review look finished.
    """
    types = [
        {
            "name": candidate.label,
            **({"parent": parent} if parent else {}),
            "description": candidate.definition or f"Proposed from {candidate.support} sources.",
            "fields": ["name", "definition"],
            "label_field": "name",
        }
        for candidate in candidates
    ]
    if not types:
        return ""
    header = (
        "# Proposed by `promote`, from candidates that passed the gate. Not a pack yet:\n"
        "# no identities have been minted, and nothing here has been read by a person.\n"
        "# Reviewing it means deciding, for each type, whether an existing vocabulary\n"
        "# already has the term -- `nearest` on each candidate is where to start.\n"
    )
    return header + yaml.safe_dump({"types": types}, allow_unicode=True, sort_keys=False)


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
