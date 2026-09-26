"""Telling a scientific disagreement apart from a mistake, and never resolving the first.

When two positions on one claim point opposite ways, exactly one of four things is
true, and treating any of them as another is a characteristic failure:

| Verdict | What it means | What it would be a mistake to do |
|---|---|---|
| `conditions` | Both are right, under different conditions | Average them, or call one refuted |
| `extraction` | One of them is not what the source says | Record it as a controversy in the field |
| `disagreement` | The sources genuinely disagree | Pick a winner |
| `ambiguous` | They are not about the same thing | Compare them at all |

This step decides between them from what the graph already holds, and the decision is
deliberately conservative: **`disagreement` is the default**, and the others have to be
earned. The order the checks run in is part of the claim. Two positions resting on the
very same words are one sentence read two ways. Recorded conditions that differ make it
`conditions` -- and that is checked *before* the source, because one paper reporting an
effect under one set of conditions and none under another is the conditions case, not a
paper contradicting itself. Only then does one source taking both sides under the same
recorded conditions become `ambiguous`.

Nothing here holds a vote, and no verdict removes anything from a store: a reconciled
conflict is a record about two positions that both remain exactly where they were.

The one thing this step must never do is make a disagreement disappear, which is why
`disagreement` is what you get when nothing else is established rather than what you get
when two models agree it is one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Node
from atlas.steps import State, register
from atlas.steps.compare import OWN
from atlas.steps.entail import implied, widen
from atlas.steps.graph_expand import Bundle, annotate
from atlas.text import normalise
from atlas.walk import Adjacency

Verdict = Literal["conditions", "extraction", "disagreement", "ambiguous"]
"""What is true about two opposed positions on one claim."""


class Conflict(Frozen):
    """Two opposed positions on one claim, with what was established about the pair."""

    about: str = Field(description="Id of the claim both positions are about")
    supporting: str
    opposing: str
    verdict: Verdict
    reason: str
    conditions: tuple[str, ...] = Field(
        default=(), description="Condition fields that differ, where that is the verdict"
    )

    @property
    def settled(self) -> bool:
        """Whether the pair turned out not to be a disagreement about the world after all."""
        return self.verdict in ("extraction", "ambiguous")


class ReconcileOptions(Frozen):
    """Which relations carry the two directions, and which fields count as conditions."""

    supports: tuple[str, ...] = Field(min_length=1)
    opposes: tuple[str, ...] = Field(min_length=1)
    conditions: tuple[str, ...] = Field(default=(), description="Relations reaching conditions")
    fields: tuple[str, ...] = Field(default=("conditions",))
    own: bool = Field(True, description=OWN)


@register("reconcile", requires=("bundle", "store"),
          produces=("conflicts", "disagreements", "bundle"), options=ReconcileOptions)
def reconcile(state: State, options: ReconcileOptions) -> State:
    """Pair up the opposed positions of the package and say what is true about each pair."""
    bundle: Bundle = state["bundle"]
    store = state["store"]
    adjacency = Adjacency.of(implied(state))
    options = options.model_copy(update={"conditions": widen(state, options.conditions)})
    held = {node.id: node for node in store.nodes()}
    for node in bundle.nodes:
        held.setdefault(node.id, node)
    for_ = _sides(bundle, options.supports)
    against = _sides(bundle, options.opposes)
    found = tuple(
        _reconcile(about, one, other, held, adjacency, options)
        for about in sorted(set(for_) & set(against))
        for one in for_[about]
        for other in against[about]
    )
    said: dict[str, str] = {}
    for one in found:
        for side, other in ((one.supporting, one.opposing), (one.opposing, one.supporting)):
            verdict = f"{one.verdict} with the position {other} takes: {one.reason}"
            said[side] = f"{said[side]}; {verdict}" if side in said else verdict
    return {"conflicts": found,
            "disagreements": sum(one.verdict == "disagreement" for one in found),
            "bundle": annotate(bundle, said)}


def _sides(bundle: Bundle, predicates: tuple[str, ...]) -> dict[str, list[str]]:
    """Which positions point at which claim, under the relations naming one direction."""
    found: dict[str, list[str]] = {}
    for link in bundle.links:
        if link.predicate in predicates:
            found.setdefault(link.dst, []).append(link.src)
    return found


def _reconcile(
    about: str,
    supporting: str,
    opposing: str,
    held: Mapping[str, Node],
    adjacency: Adjacency,
    options: ReconcileOptions,
) -> Conflict:
    """The verdict on one pair, from what the graph holds and nothing else."""
    one, other = held.get(supporting), held.get(opposing)
    if one is None or other is None:
        return Conflict(about=about, supporting=supporting, opposing=opposing,
                        verdict="ambiguous",
                        reason="one of the two positions is not in the store")

    # Order matters here, and it is not the obvious one. Two positions resting on the
    # very same words are one sentence read two ways, whatever else is true of them.
    if one.spans[0].text.strip() == other.spans[0].text.strip():
        return Conflict(about=about, supporting=supporting, opposing=opposing,
                        verdict="extraction",
                        reason="both positions rest on the same words, read two ways")

    # Conditions are checked before the source, because one paper reporting an effect
    # under one set of conditions and no effect under another is the conditions case
    # and not a paper contradicting itself. Checking the source first would have hidden
    # exactly the finding this architecture exists to record.
    differing = _differing(one, other, held, adjacency, options)
    if differing:
        return Conflict(about=about, supporting=supporting, opposing=opposing,
                        verdict="conditions", conditions=differing,
                        reason=f"recorded conditions differ: {', '.join(differing)}")

    here, there = one.spans[0].source_id, other.spans[0].source_id
    if here == there:
        return Conflict(about=about, supporting=supporting, opposing=opposing,
                        verdict="ambiguous",
                        reason=f"both positions were cut from {here!r} under the same "
                               "recorded conditions")

    # Nothing established anything else, so it stands as what it looks like. This is the
    # default on purpose: a disagreement has to be explained away, not voted away.
    return Conflict(about=about, supporting=supporting, opposing=opposing,
                    verdict="disagreement",
                    reason=f"{here!r} and {there!r} take opposite positions on the same claim")


def _differing(
    one: Node,
    other: Node,
    held: Mapping[str, Node],
    adjacency: Adjacency,
    options: ReconcileOptions,
) -> tuple[str, ...]:
    """The condition fields the two positions record different values for."""
    here = _conditions(one, held, adjacency, options)
    there = _conditions(other, held, adjacency, options)
    return tuple(sorted(
        key for key in here if here[key] and there.get(key) and here[key] != there[key]
    ))


def _conditions(
    node: Node, held: Mapping[str, Node], adjacency: Adjacency, options: ReconcileOptions
) -> dict[str, str]:
    """A position's conditions: its own fields, plus those of everything it reaches."""
    found = {
        field: normalise(node.fields.get(field, "")) if options.own else ""
        for field in options.fields
    }
    frontier = [node.id]
    seen = {node.id}
    for _hop in range(2):
        onward = []
        for node_id in frontier:
            for edge in adjacency.edges(node_id, backward=False):
                if edge.other in seen:
                    continue
                seen.add(edge.other)
                onward.append(edge.other)
                if options.conditions and edge.predicate not in options.conditions:
                    continue
                neighbour = held.get(edge.other)
                for key, value in (neighbour.fields if neighbour else {}).items():
                    if value and not found.get(key):
                        found[key] = normalise(value)
        frontier = onward
    return found
