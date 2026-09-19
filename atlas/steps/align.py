"""Matching what was planned against what happened, and naming every place they differ.

A protocol and a run of it are two different things with two different identities, and
a record that keeps only one of them cannot answer the question that makes
irreproducibility tractable: *where did this run depart from the procedure?* This step
puts the two step lists side by side and reports four kinds of departure -- a planned
step that did not happen, a step that happened and was not planned, two steps in the
wrong order, and a step that happened under a different name.

The matching is deliberately shallow: an already-asserted `realises` link is believed,
and everything else is matched by term overlap between the step labels above a
threshold, greedily, in order. That is not clever and it is not meant to be. The value
is in the **report**, which is a list of named discrepancies somebody can read against
the paper, not in an alignment good enough to trust unread. Where the shallow matcher is
wrong, the fix is to assert the correspondence -- and then it is a link in the graph,
with a span behind it, like every other claim in this library.

A renamed step is reported as `renamed` rather than silently matched, because "the paper
calls this washing and the run calls it rinsing" is exactly the kind of difference that
turns out to matter, and a matcher that swallowed it would have hidden the finding it
was run to produce.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Node, Schema
from atlas.steps import State, register
from atlas.steps.induce import similarity
from atlas.walk import Adjacency

Departure = Literal["missing", "extra", "reordered", "renamed"]
"""The four ways a run departs from the procedure it says it followed."""


class Step(Frozen):
    """One step of either list, with the order it was given and the label it goes by."""

    node_id: str
    label: str
    order: int


class Discrepancy(Frozen):
    """One departure, named, with the steps it is about."""

    kind: Departure
    planned: Step | None = None
    actual: Step | None = None
    detail: str = ""


class AlignOptions(Frozen):
    """Which types are the two lists, which relations reach them, and how close a match is.

    Everything is the pack's vocabulary and arrives as configuration. `asserted` names
    the relation by which a correspondence somebody has already established is
    believed, which is what makes a wrong shallow match fixable in the data rather than
    in the code.
    """

    plan: str = Field(min_length=1, description="Type of the steps as planned")
    run: str = Field(min_length=1, description="Type of the steps as carried out")
    asserted: tuple[str, ...] = Field(default=(), description="Relations already matching the two")
    order_field: str = "order"
    threshold: float = Field(0.5, ge=0.0, le=1.0)


@register("align", requires=("store",), produces=("alignment", "discrepancies"),
          options=AlignOptions)
def align(state: State, options: AlignOptions) -> State:
    """Put the planned steps beside the ones that happened and report every departure."""
    store = state["store"]
    schema: Schema | None = state.get("schema")
    nodes = store.nodes()
    planned = _steps(nodes, options.plan, schema, options.order_field)
    actual = _steps(nodes, options.run, schema, options.order_field)
    believed = _believed(Adjacency.of(store.links(), options.asserted))
    matched, found = _match(planned, actual, believed, options.threshold)
    return {"alignment": matched, "discrepancies": found}


def _match(
    planned: list[Step],
    actual: list[Step],
    believed: Mapping[str, str],
    threshold: float,
) -> tuple[tuple[tuple[Step, Step], ...], tuple[Discrepancy, ...]]:
    """Pair the two lists up and name what is left over on either side."""
    pairs: list[tuple[Step, Step]] = []
    found: list[Discrepancy] = []
    left = list(actual)
    for step in planned:
        partner = _partner(step, left, believed, threshold)
        if partner is None:
            found.append(Discrepancy(kind="missing", planned=step,
                                     detail="planned, and no step of the run matches it"))
            continue
        left.remove(partner)
        pairs.append((step, partner))
        renamed = similarity(step.label, partner.label) < 1.0
        if renamed and believed.get(partner.node_id) != step.node_id:
            found.append(Discrepancy(
                kind="renamed", planned=step, actual=partner,
                detail=f"{step.label!r} planned, {partner.label!r} carried out",
            ))
    found += [
        Discrepancy(kind="extra", actual=step,
                    detail="carried out, and the procedure has no such step")
        for step in left
    ]
    found += _reordered(pairs)
    return tuple(pairs), tuple(found)


def _partner(
    step: Step, left: list[Step], believed: Mapping[str, str], threshold: float
) -> Step | None:
    """The run step this planned step matches: an asserted one first, then the closest label."""
    asserted = next((one for one in left if believed.get(one.node_id) == step.node_id), None)
    if asserted is not None:
        return asserted
    scored = [(similarity(step.label, one.label), one) for one in left]
    best = max(scored, key=lambda pair: (pair[0], -pair[1].order), default=(0.0, None))
    return best[1] if best[0] >= threshold else None


def _reordered(pairs: Iterable[tuple[Step, Step]]) -> list[Discrepancy]:
    """Pairs whose order in the run does not follow their order in the procedure."""
    ordered = sorted(pairs, key=lambda pair: pair[0].order)
    found = []
    for (before, ran_before), (after, ran_after) in zip(ordered, ordered[1:], strict=False):
        if ran_before.order > ran_after.order:
            found.append(Discrepancy(
                kind="reordered", planned=after, actual=ran_after,
                detail=f"planned after {before.label!r}, carried out before it",
            ))
    return found


def _believed(adjacency: Adjacency) -> dict[str, str]:
    """Correspondences somebody has already asserted, as run step to planned step."""
    return {link.src: link.dst for link in adjacency.links.values()}


def _steps(
    nodes: Iterable[Node], type_name: str, schema: Schema | None, order_field: str
) -> list[Step]:
    """Every node of one of the two types, in the order the pack's order field gives."""
    held = [
        node for node in nodes
        if (schema.is_a(node.type, type_name) if schema else node.type == type_name)
    ]
    steps = [
        Step(node_id=node.id, label=schema.label_of(node) if schema else node.type,
             order=_order(node, order_field, index))
        for index, node in enumerate(held)
    ]
    return sorted(steps, key=lambda step: (step.order, step.node_id))


def _order(node: Node, field: str, fallback: int) -> int:
    """The order a step declares, or where it happened to be found if it declares none."""
    try:
        return int(node.fields.get(field, ""))
    except ValueError:
        return fallback
