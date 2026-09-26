"""Tests for deciding which results may be put beside each other.

The three rules the module states are the three under test, and each of them is a way a
comparison quietly goes wrong: a condition nobody recorded is not a condition that
matched, a unit nothing declared a conversion for makes two values incomparable rather
than equal, and an asserted comparability is believed but still reported.
"""

from __future__ import annotations

from atlas.model import Node
from atlas.steps.compare import CompareOptions, compare, convert
from atlas.steps.graph_expand import GraphExpandOptions, expand
from conftest import Fixture

OPTIONS = CompareOptions(type="StudyResult", conditions=("observed_under",),
                         fields=("conditions",))


def state(science: Fixture) -> dict:
    return {
        "bundle": expand(science.store, [science.nodes["claim"].id],
                         GraphExpandOptions(depth=3, limit=40)),
        "store": science.store,
        "schema": science.schema,
    }


def test_results_obtained_under_different_conditions_are_partial_at_best(
    science: Fixture,
) -> None:
    result = compare(state(science), OPTIONS)

    [comparison] = result["comparisons"]
    assert comparison.verdict == "partial"
    assert "conditions" in comparison.differed
    assert result["comparable"] == 0


def test_a_condition_nobody_recorded_is_insufficient_rather_than_matching(
    science: Fixture,
) -> None:
    made = state(science)
    # The second result loses its own condition field and its link to a Context, so
    # nothing about the conditions it was obtained under is known.
    bare = made["bundle"].node(science.nodes["result-2"].id)
    assert bare is not None
    made["bundle"] = made["bundle"].model_copy(update={
        "nodes": tuple(bare if node.id == bare.id else node for node in made["bundle"].nodes),
        "links": tuple(link for link in made["bundle"].links
                       if link.src != bare.id or link.predicate != "observed_under"),
    })
    made["store"] = _StoreWithout(science.store, bare)

    [comparison] = compare(made, OPTIONS)["comparisons"]

    assert comparison.verdict == "insufficient"
    assert set(comparison.missing) == {"conditions", "description"}
    assert "not recorded" in comparison.reason
    assert not comparison.usable


def test_an_asserted_comparability_is_believed_and_named(science: Fixture) -> None:
    asked = CompareOptions(type="StudyResult", conditions=("observed_under",),
                           comparable=("comparable_with",))

    [comparison] = compare(state(science), asked)["comparisons"]

    assert comparison.verdict == "comparable"
    assert "asserted comparable by 'comparable_with'" in comparison.reason
    # Believed, and still reported: the conditions that differ are in the record.
    assert comparison.differed == ("conditions", "description")


def test_a_package_holding_no_results_compares_nothing(science: Fixture) -> None:
    made = state(science)
    made["bundle"] = made["bundle"].model_copy(update={"nodes": ()})

    assert compare(made, OPTIONS)["comparisons"] == ()


def test_a_declared_conversion_is_applied_and_carries_what_it_cost() -> None:
    converted = convert("0.5", "m", "cm", {"m:cm": 100.0})

    assert converted is not None
    assert (converted.value, converted.unit, converted.was) == ("50", "cm", "m")
    assert converted.factor == 100.0


def test_a_conversion_declared_one_way_round_is_read_both_ways() -> None:
    converted = convert("50", "cm", "m", {"m:cm": 100.0})

    assert converted is not None
    assert converted.value == "0.5"


def test_an_undeclared_unit_pair_converts_to_nothing() -> None:
    assert convert("50", "cm", "furlong", {"m:cm": 100.0}) is None


def test_a_value_that_is_not_a_number_converts_to_nothing() -> None:
    assert convert("about half", "m", "cm", {"m:cm": 100.0}) is None


def test_two_values_in_units_nothing_declares_a_way_between_are_insufficient(
    science: Fixture,
) -> None:
    made = state(science)
    made["bundle"] = made["bundle"].model_copy(update={
        "nodes": tuple(
            node.model_copy(update={"fields": {**node.fields, "unit": _unit(node)}})
            if node.type == "StudyResult" else node
            for node in made["bundle"].nodes
        )
    })

    [comparison] = compare(made, OPTIONS)["comparisons"]

    assert comparison.verdict == "insufficient"
    assert "no declared conversion" in comparison.reason


def _unit(node: Node) -> str:
    return "percent" if node.fields.get("value") == "0.94" else "fraction"


class _StoreWithout:
    """The fixture store with one node replaced, to stand for a source that recorded less."""

    def __init__(self, store: object, node: Node) -> None:
        self._store = store
        self._node = node

    def nodes(self) -> tuple[Node, ...]:
        return tuple(self._node if one.id == self._node.id else one
                     for one in self._store.nodes())

    def links(self):
        return tuple(link for link in self._store.links()
                     if not (link.src == self._node.id and link.predicate == "observed_under"))


def test_a_baseline_that_recorded_nothing_does_not_find_that_everything_agrees(
    science: Fixture,
) -> None:
    made = state(science)
    made["store"] = _StoreWithout(science.store, science.nodes["result-1"])

    [comparison] = compare(made, OPTIONS)["comparisons"]

    # Whichever of the two is taken as the baseline, one side knows nothing, and the
    # verdict has to reflect that rather than the side that happens to be first.
    assert comparison.verdict == "insufficient"


def test_a_condition_the_ontology_carries_to_a_result_is_compared_on() -> None:
    """Nobody linked the results to a condition; the RL chain did, and compare reads it.

    `obtained_under` is `yielded` read backwards and then `under_condition`, and it is a
    kind of `observed_under` -- so a configuration asking for `observed_under` compares the
    two results on the conditions of the runs that yielded them, and each such relation is
    marked as derived.
    """
    from atlas.model import Agent, Assertion, Link, Segment, Source, Span
    from atlas.ontology import load
    from atlas.steps.entail import EntailOptions, entail
    from atlas.steps.graph_expand import Bundle
    from atlas.store.memory import MemoryStore

    text = "Run A at 20 C yielded 0.91. Run B at 20 C yielded 0.88."
    source = Source(id="p", origin="p.txt", segments=(Segment(number=1, text=text),))
    schema = load("process_rl")

    def made(node_id: str, type_name: str, quote: str, **fields: str) -> Node:
        start = text.index(quote)
        return Node(id=node_id, type=type_name, fields=fields,
                    spans=(Span.of(source, 1, start, start + len(quote)),),
                    schema_version=schema.version)

    nodes = [made("r1", "StudyResult", "0.91", value="0.91"),
             made("r2", "StudyResult", "0.88", value="0.88"),
             made("e1", "Experiment", "Run A", name="A"),
             made("e2", "Experiment", "Run B", name="B"),
             made("c1", "ExperimentalCondition", "20 C", name="temperature 20", unit="C"),
             made("c2", "ExperimentalCondition", "at 20 C", name="temperature 20", unit="C")]
    wiring = [("e1", "yielded", "r1"), ("e2", "yielded", "r2"),
              ("e1", "under_condition", "c1"), ("e2", "under_condition", "c2")]
    store = MemoryStore()
    store.add_source(source)
    agent = Agent(id="run", kind="run")
    for index, target in enumerate([*nodes, *(
            Link.of(predicate=p, src=a, dst=b, spans=nodes[0].spans,
                    schema_version=schema.version) for a, p, b in wiring)]):
        store.assert_(Assertion(id=f"a{index}", agent=agent, at="2026-01-01T00:00:00+00:00",
                                target=target))
    state = {"store": store, "schema": schema}
    state |= entail(state, EntailOptions())
    state["bundle"] = Bundle(roots=("r1",), nodes=tuple(store.get_nodes(["r1", "r2"])))

    result = compare(state, CompareOptions(type="StudyResult", conditions=("observed_under",),
                                           fields=("name", "unit")))

    assert {one.predicate for one in state["derived"]} >= {"obtained_under"}
    assert [one.verdict for one in result["comparisons"]] == ["comparable"]
    assert result["comparisons"][0].matched == ("name", "unit")


def test_a_results_own_wording_is_not_a_condition_when_the_ontology_says_so(
    science: Fixture,
) -> None:
    """Two results that say different things are not results obtained under different
    conditions; with `own` off, only what the result reaches is compared."""
    own = CompareOptions(type="StudyResult", conditions=("observed_under",),
                         fields=("statement",))
    [by_wording] = compare(state(science), own)["comparisons"]
    assert "statement" in by_wording.differed

    reached = own.model_copy(update={"own": False})
    [by_conditions] = compare(state(science), reached)["comparisons"]
    assert "statement" not in by_conditions.differed


def test_the_verdicts_are_written_into_the_package_where_the_answer_reads_them(
    science: Fixture,
) -> None:
    """A comparison computed and then left in a state key the answer never reads is a
    comparison nobody sees; the verdict goes beside the reason each result is there."""
    result = compare(state(science), OPTIONS)

    reasons = result["bundle"].reasons
    [one] = result["comparisons"]
    [baseline] = {science.nodes["result-1"].id, science.nodes["result-2"].id} - {one.node_id}
    assert "compared against" in reasons[baseline]
    assert reasons[one.node_id].startswith(f"{one.verdict} against the baseline")
