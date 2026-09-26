"""Deciding which results may be put beside each other, and reporting why the rest may not.

The question a process-centred Atlas exists to answer is *under what conditions*, and
the way that question is usually got wrong is by averaging. Two numbers about the same
quantity, obtained under conditions nobody checked, are not two measurements of one
thing; a mean over them is a number with no referent. So this step never merges
anything. It sorts the results of a package into three groups and says, for every
result it excluded, which condition it was excluded on.

Three rules, each of which is a way a comparison quietly goes wrong:

**Unknown is not equal.** A result whose condition was never recorded is *insufficient*,
not *comparable*. This is the rule that matters most and the one that costs the most
results, which is why it is first: a corpus where most conditions are not reported will
say so loudly instead of producing a confident average over nothing.

**A conversion is an act with provenance.** Two values in different units are comparable
only through a conversion the configuration declared, and a converted value carries the
factor it went through and the unit it started in. Nothing is converted silently, and a
unit pair nobody declared makes the two results incomparable rather than assumed equal.

**Comparability can be asserted.** Where somebody -- a person, an earlier run, a source
-- has said two sets of conditions are comparable, that is a link in the graph like
anything else, and the configuration names the predicate. It is evidence, not a
shortcut: the conditions are still reported, and the assertion is named in the reason.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Node
from atlas.steps import State, register
from atlas.steps.entail import implied, widen
from atlas.steps.graph_expand import Bundle
from atlas.text import normalise
from atlas.walk import Adjacency

OWN = (
    "Whether a result's own fields count among its conditions. Off for an ontology in which "
    "every class states itself in one shared field -- a formulation, a statement -- where a "
    "result's own wording is not a condition of it, and reading it as one compares two "
    "results by what they say rather than by what they were obtained under."
)

Verdict = Literal["comparable", "partial", "insufficient"]
"""What may be said about two results side by side: everything matched, some of it did,
or something needed was never recorded."""


class Conversion(Frozen):
    """One declared way of putting a value into another unit, and what it cost to do it."""

    value: str
    unit: str
    factor: float
    was: str = Field(description="The unit the value was written in before conversion")


class Comparison(Frozen):
    """One result against the baseline, with the verdict and the conditions behind it."""

    node_id: str
    verdict: Verdict
    matched: tuple[str, ...] = ()
    differed: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    reason: str = ""
    converted: Conversion | None = None

    @property
    def usable(self) -> bool:
        """Whether this result may be put beside the baseline at all."""
        return self.verdict != "insufficient"


class CompareOptions(Frozen):
    """Which types are results, which relation leads to their conditions, and what converts.

    Everything here is the ontology's vocabulary and arrives as configuration. `conditions`
    is the relation from a result to the thing describing what it was obtained under;
    `fields` are the condition fields that have to agree; `units` is the declared
    conversion table, written as `from:to` to a factor.
    """

    type: str = Field(min_length=1, description="The ontology type whose instances are compared")
    conditions: tuple[str, ...] = Field(default=(), description="Relations leading to conditions")
    fields: tuple[str, ...] = Field(default=("conditions",))
    own: bool = Field(True, description=OWN)
    value_field: str = "value"
    unit_field: str = "unit"
    comparable: tuple[str, ...] = Field(
        default=(), description="Relations asserting that two conditions were checked and match"
    )
    units: dict[str, float] = Field(
        default_factory=dict, description="Declared conversions, `from:to` to a factor"
    )


@register("compare", requires=("bundle", "store"), produces=("comparisons", "comparable"),
          options=CompareOptions)
def compare(state: State, options: CompareOptions) -> State:
    """Sort the results of the package against the first of them, and report every exclusion."""
    bundle: Bundle = state["bundle"]
    schema = state.get("schema")
    results = [
        node for node in bundle.nodes
        if (schema.is_a(node.type, options.type) if schema else node.type == options.type)
    ]
    if not results:
        return {"comparisons": (), "comparable": 0}
    # The graph as the ontology makes it: a condition reached through a relation the
    # ontology puts under a named one, or through a link the engine derived, counts.
    options = options.model_copy(update={"conditions": widen(state, options.conditions),
                                         "comparable": widen(state, options.comparable)})
    links = implied(state)
    adjacency = Adjacency.of(links)
    held = {node.id: node for node in state["store"].nodes()}
    conditions = {
        node.id: _conditions(node, adjacency, held, options) for node in results
    }
    asserted = _asserted(results, adjacency, options)
    baseline, rest = results[0], results[1:]
    found = tuple(
        _compare(baseline, other, conditions, asserted, options) for other in rest
    )
    return {"comparisons": found, "comparable": sum(one.verdict == "comparable" for one in found)}


def convert(value: str, unit: str, into: str, table: Mapping[str, float]) -> Conversion | None:
    """The value in another unit, if the configuration declared the conversion; else None.

    Declared one way round and read both ways, because a table that had to list metres
    to centimetres and centimetres to metres would eventually list one of them wrong.
    """
    if unit == into:
        return None
    factor = table.get(f"{unit}:{into}")
    if factor is None:
        inverse = table.get(f"{into}:{unit}")
        factor = 1 / inverse if inverse else None
    if factor is None:
        return None
    try:
        converted = float(value.replace(",", ".")) * factor
    except ValueError:
        return None
    return Conversion(value=f"{converted:g}", unit=into, factor=factor, was=unit)


def _compare(
    baseline: Node,
    other: Node,
    conditions: Mapping[str, dict[str, str]],
    asserted: Mapping[tuple[str, str], str],
    options: CompareOptions,
) -> Comparison:
    """One result against the baseline: what agreed, what differed, what was never recorded."""
    here, there = conditions[baseline.id], conditions[other.id]
    # Both sides are read, not just the baseline's. A baseline that recorded nothing
    # would otherwise find that every condition it knows about agrees, which is true
    # and is the most misleading thing this step could say.
    keys = {key for key in (*here, *there) if here.get(key) or there.get(key)}
    matched = tuple(sorted(
        key for key in keys if here.get(key) and here[key] == there.get(key)
    ))
    differed = tuple(sorted(
        key for key in keys if here.get(key) and there.get(key) and here[key] != there[key]
    ))
    missing = tuple(sorted(key for key in keys if not here.get(key) or not there.get(key)))
    converted = convert(
        other.fields.get(options.value_field, ""),
        other.fields.get(options.unit_field, ""),
        baseline.fields.get(options.unit_field, ""),
        options.units,
    )
    if _incomparable_units(baseline, other, converted, options):
        return Comparison(node_id=other.id, verdict="insufficient", matched=matched,
                          differed=differed, missing=missing,
                          reason=f"no declared conversion from "
                                 f"{other.fields.get(options.unit_field, '')!r} to "
                                 f"{baseline.fields.get(options.unit_field, '')!r}")
    by = asserted.get((baseline.id, other.id))
    if by:
        return Comparison(node_id=other.id, verdict="comparable", matched=matched,
                          differed=differed, missing=missing, converted=converted,
                          reason=f"conditions asserted comparable by {by!r}")
    # Unknown is not equal, and it is checked before difference: a condition nobody
    # recorded is a hole in the evidence, which is a stronger statement than a mismatch.
    if missing:
        return Comparison(node_id=other.id, verdict="insufficient", matched=matched,
                          differed=differed, missing=missing, converted=converted,
                          reason=f"conditions not recorded: {', '.join(missing)}")
    if differed:
        return Comparison(node_id=other.id, verdict="partial", matched=matched,
                          differed=differed, converted=converted,
                          reason=f"conditions differ: {', '.join(differed)}")
    return Comparison(node_id=other.id, verdict="comparable", matched=matched,
                      converted=converted, reason="every recorded condition agrees")


def _incomparable_units(
    baseline: Node, other: Node, converted: Conversion | None, options: CompareOptions
) -> bool:
    """Whether the two values are in units nothing declared a way between."""
    here = baseline.fields.get(options.unit_field, "")
    there = other.fields.get(options.unit_field, "")
    return bool(here) and bool(there) and here != there and converted is None


def _conditions(
    node: Node, adjacency: Adjacency, held: Mapping[str, Node], options: CompareOptions
) -> dict[str, str]:
    """Every condition of one result: its own fields, plus those of what it points at."""
    found = {
        field: normalise(node.fields.get(field, "")) if options.own else ""
        for field in options.fields
    }
    for edge in adjacency.edges(node.id, backward=False):
        if options.conditions and edge.predicate not in options.conditions:
            continue
        neighbour = held.get(edge.other)
        if neighbour is None:
            continue
        for key, value in neighbour.fields.items():
            if value and not found.get(key):
                found[key] = normalise(value)
    return found


def _asserted(
    results: Iterable[Node],
    adjacency: Adjacency,
    options: CompareOptions,
) -> dict[tuple[str, str], str]:
    """Pairs of results whose conditions something has asserted to be comparable.

    The assertion is made between the conditions and not between the results, because
    that is the thing somebody can actually check: two runs are comparable when what
    they were run under was compared. So each result's conditions are collected, and a
    pair of results is asserted-comparable when a declared relation joins one result's
    conditions to the other's.
    """
    if not options.comparable:
        return {}
    conditions = {
        node.id: {
            edge.other
            for edge in adjacency.edges(node.id, backward=False)
            if not options.conditions or edge.predicate in options.conditions
        }
        for node in results
    }
    declared: dict[tuple[str, str], str] = {}
    for link in adjacency.links.values():
        if link.predicate in options.comparable:
            declared[(link.src, link.dst)] = link.predicate
            declared[(link.dst, link.src)] = link.predicate
    found: dict[tuple[str, str], str] = {}
    for one, here in conditions.items():
        for other, there in conditions.items():
            if one == other:
                continue
            named = next(
                (declared[(a, b)] for a in here for b in there if (a, b) in declared), ""
            )
            if named:
                found[(one, other)] = named
    return found
