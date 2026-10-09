"""Strict operator contracts for generated plans; the static baseline remains available."""

from __future__ import annotations

import pytest

from atlas.model import Agent, Assertion, Link
from atlas.steps.graph_expand import GraphExpandOptions
from atlas.steps.plan import Operator, PlanOptions, PlanRefused, check_strict, execute_plan, run
from conftest import Fixture


def options(*operators: Operator, **over) -> PlanOptions:
    return PlanOptions(plan=operators, strict=True, **over)


def test_a_composition_keeps_filter_inputs_exclusions_and_relation_witnesses(science: Fixture):
    trace = run(science.store, science.schema, options(
        Operator(op="resolve", type="StudyResult"),
        Operator(op="filter", field="value", value="0.94"),
        Operator(op="aggregate"),
        Operator(op="traverse", predicate="observed_under"),
        Operator(op="compare", field="conditions"),
    ))
    assert not trace.partial
    assert set(trace.steps[1].inputs) == {science.nodes[f"result-{n}"].id for n in (1, 2)}
    assert trace.steps[1].excluded == (science.nodes["result-2"].id,)
    assert trace.steps[2].count == 1
    assert trace.steps[3].witnesses == (science.links["result-1-observed_under-u1"].id,)
    assert trace.steps[4].groups == {"u1": (science.nodes["u1"].id,)}


@pytest.mark.parametrize("plan, reason", [
    ((), "start with resolve"),
    ((Operator(op="resolve"), Operator(op="aggregate", value="unknown")),
     "unsupported aggregate population"),
    ((Operator(op="resolve", type="StudyResult"),
      Operator(op="filter", field="absent")), "not declared"),
    ((Operator(op="resolve", type="StudyResult"),
      Operator(op="traverse", predicate="supports")), "endpoint"),
    ((Operator(op="resolve", type="StudyResult"),
      Operator(op="compare")), "field to compare"),
    ((Operator(op="resolve", type="StudyResult", field="value"),), "unused argument"),
    ((Operator(op="resolve", type="StudyResult"),
      Operator(op="filter", type="Context", field="conditions")), "incompatible"),
])
def test_invalid_contracts_are_refused_before_store_reads(science: Fixture, plan, reason):
    class NoReads:
        def nodes(self):
            raise AssertionError("an invalid plan read the graph")

    assert any(reason in problem for problem in check_strict(plan, science.schema))
    with pytest.raises(PlanRefused, match=reason) as caught:
        execute_plan({"store": NoReads(), "schema": science.schema}, options(*plan))
    assert caught.value.category == "schema"


@pytest.mark.parametrize("over, reason", [
    ({"max_steps": 1}, "operator budget"),
    ({"max_graph_nodes": 1}, "graph exceeds the node budget"),
    ({"max_graph_links": 1}, "link budget"),
    ({"limit": 1}, "exceeds the node budget"),
])
def test_a_budget_refuses_instead_of_returning_a_sampled_aggregate(science: Fixture, over, reason):
    with pytest.raises(PlanRefused, match=reason) as caught:
        run(science.store, science.schema, options(
            Operator(op="resolve", type="StudyResult"), Operator(op="aggregate"), **over,
        ))
    assert caught.value.category == "budget"


def test_an_empty_population_has_an_exact_zero_count(science: Fixture):
    result = execute_plan({"store": science.store, "schema": science.schema}, options(
        Operator(op="resolve", type="StudyResult", terms=("no-such-text",)),
        Operator(op="aggregate"),
    ))
    assert result["answer_count"] == 0
    assert result["trace"].steps[-1].count == 0
    assert not result["trace"].partial


def test_strict_plans_canonicalise_class_and_relation_identities(science: Fixture):
    root = science.schema.find_type("StudyResult")
    predicate = science.schema.find_predicate("observed_under")
    assert root and root.iri and predicate and predicate.iri
    result = run(science.store, science.schema, options(
        Operator(op="resolve", type=root.iri),
        Operator(op="traverse", predicate=predicate.iri),
    ))
    assert len(result.steps[-1].nodes) == 2
    assert result.steps[0].operator.type == root.name
    assert result.steps[1].operator.predicate == predicate.name


def test_an_opposition_predicate_without_a_configured_role_is_an_operator_gap(science: Fixture):
    with pytest.raises(PlanRefused) as caught:
        run(science.store, science.schema, options(
            Operator(op="resolve", type="StudyResult"),
            Operator(op="oppose", predicate="observed_under"),
        ))
    assert caught.value.category == "operator"


def test_a_strict_execution_does_not_assert_anything(science: Fixture):
    before = tuple(science.store.assertions())
    execute_plan({"store": science.store, "schema": science.schema}, options(
        Operator(op="resolve", type="StudyResult"), Operator(op="aggregate"),
    ))
    assert tuple(science.store.assertions()) == before


def test_source_aggregate_deduplicates_all_verbatim_spans_and_preserves_node_witnesses(
    science: Fixture,
):
    trace = run(science.store, science.schema, options(
        Operator(op="resolve"), Operator(op="aggregate", value="sources"),
    ))
    population = trace.steps[0].nodes
    expected: dict[str, set[str]] = {}
    held = {node.id: node for node in science.store.nodes()}
    for node_id in population:
        for span in held[node_id].spans:
            expected.setdefault(span.source_id, set()).add(node_id)
    result = trace.steps[1]
    assert len(population) > len(expected)
    assert result.count == len(expected)
    assert result.nodes == population
    assert result.groups == {key: tuple(sorted(nodes)) for key, nodes in sorted(expected.items())}


def test_source_aggregate_of_an_empty_selection_is_exact_zero(science: Fixture):
    trace = run(science.store, science.schema, options(
        Operator(op="resolve", terms=("no-such-text",)),
        Operator(op="aggregate", value="sources"),
    ))
    assert trace.steps[-1].count == 0
    assert trace.steps[-1].groups == {}


def test_full_graph_resolution_preserves_class_flow_checks(science: Fixture):
    problems = check_strict((Operator(op="resolve"),
                            Operator(op="filter", field="value")), science.schema)
    assert problems


def test_join_keeps_anchors_with_matching_objects_and_their_pairs(science: Fixture):
    trace = run(science.store, science.schema, options(
        Operator(op="resolve", type="StudyResult"),
        Operator(op="join", predicate="observed_under", type="Context",
                 field="conditions", value="U1"),
        Operator(op="aggregate"), Operator(op="compare", field="value"),
    ))
    result, context = science.nodes["result-1"].id, science.nodes["u1"].id
    joined = trace.steps[1]
    assert joined.nodes == (result,)
    assert joined.groups == {result: (context,)}
    assert joined.excluded == (science.nodes["result-2"].id,)
    assert joined.witnesses == (science.links["result-1-observed_under-u1"].id,)
    assert trace.steps[2].count == 1
    assert trace.steps[3].groups == {"0.94": (result,)}


def test_join_pair_multiplicity_never_duplicates_an_anchor(science: Fixture):
    link = Link.of(predicate="observed_under", src=science.nodes["result-1"].id,
        dst=science.nodes["u2"].id, spans=science.nodes["result-1"].spans,
        schema_version=science.schema.version)
    science.store.assert_(Assertion(id="join-extra-link", target=link,
        agent=Agent(id="fixture", kind="run"), at="2026-10-07T00:00:00Z"))
    trace = run(science.store, science.schema, options(
        Operator(op="resolve", type="StudyResult"),
        Operator(op="join", predicate="observed_under"), Operator(op="aggregate"),
    ))
    assert sum(len(one) for one in trace.steps[1].groups.values()) == 3
    assert len(trace.steps[1].witnesses) == 3
    assert trace.steps[2].count == 2


def test_join_can_match_backwards_and_retains_the_original_class_flow(science: Fixture):
    trace = run(science.store, science.schema, options(
        Operator(op="resolve", type="Context"),
        Operator(op="join", predicate="observed_under", forward=False,
                 type="StudyResult", field="value", value="0.94"),
        Operator(op="compare", field="conditions"),
    ))
    assert trace.steps[1].nodes == (science.nodes["u1"].id,)
    assert trace.steps[2].groups == {"u1": (science.nodes["u1"].id,)}


@pytest.mark.parametrize("over, reason", [
    ({"field": "value"}, "matched field"),
    ({"type": "StudyResult"}, "matched class"),
    ({"value": "value-without-field"}, "value needs a field"),
])
def test_join_checks_its_matched_side_before_reads(science: Fixture, over, reason):
    class NoReads:
        def nodes(self):
            raise AssertionError("an invalid join read graph data")

    with pytest.raises(PlanRefused, match=reason):
        execute_plan({"store": NoReads(), "schema": science.schema}, options(
            Operator(op="resolve", type="StudyResult"),
            Operator(op="join", predicate="observed_under", **over),
        ))


def test_opposition_preserves_both_sides_and_excludes_support_links(science: Fixture):
    before = tuple(science.store.assertions())
    trace = run(science.store, science.schema, options(
        Operator(op="resolve", type="Proposition"),
        Operator(op="oppose", predicate="disputes"), Operator(op="aggregate"),
        expand=GraphExpandOptions(opposes=("disputes",)),
    ))
    assert set(trace.steps[1].nodes) == {science.nodes["claim"].id,
                                        science.nodes["line-against"].id}
    assert trace.steps[1].witnesses == (science.links["line-against-disputes-claim"].id,)
    assert trace.steps[2].count == 2
    assert tuple(science.store.assertions()) == before


def test_opposition_budget_refuses_instead_of_returning_one_side(science: Fixture):
    with pytest.raises(PlanRefused, match="opposition closure") as caught:
        run(science.store, science.schema, options(
            Operator(op="resolve", type="Proposition"),
            Operator(op="oppose", predicate="disputes"), Operator(op="aggregate"), limit=1,
            expand=GraphExpandOptions(opposes=("disputes",)),
        ))
    assert caught.value.category == "budget"


def test_opposition_role_and_operator_can_use_iris(science: Fixture):
    iri = science.schema.find_predicate("disputes").iri
    trace = run(science.store, science.schema, options(
        Operator(op="resolve", type="Proposition"), Operator(op="oppose", predicate=iri),
        expand=GraphExpandOptions(opposes=(iri,)),
    ))
    assert trace.steps[1].operator.predicate == "disputes"
    assert len(trace.steps[1].nodes) == 2


def test_opposition_is_a_component_walk_instead_of_a_one_hop_alias(science: Fixture):
    source = science.nodes["line-for"]
    extra = Link.of(predicate="disputes", src=source.id, dst=science.nodes["claim"].id,
        spans=source.spans, schema_version=science.schema.version)
    science.store.assert_(Assertion(id="opposition-extra-link", target=extra,
        agent=Agent(id="fixture", kind="run"), at="2026-10-07T00:00:00Z"))
    trace = run(science.store, science.schema, options(
        Operator(op="resolve", type="EvidenceLine", terms=("no effect",)),
        Operator(op="oppose", predicate="disputes"),
        expand=GraphExpandOptions(opposes=("disputes",)),
    ))
    assert trace.steps[0].nodes == (science.nodes["line-against"].id,)
    assert set(trace.steps[1].nodes) == {source.id, science.nodes["claim"].id,
                                        science.nodes["line-against"].id}
    assert set(trace.steps[1].witnesses) == {
        extra.id, science.links["line-against-disputes-claim"].id}


def test_an_empty_join_has_zero_aggregate_and_visible_exclusions(science: Fixture):
    trace = run(science.store, science.schema, options(
        Operator(op="resolve", type="StudyResult"),
        Operator(op="join", predicate="observed_under", field="conditions", value="absent"),
        Operator(op="aggregate"),
    ))
    assert trace.emptied_at is trace.steps[1]
    assert trace.steps[1].excluded == trace.steps[1].inputs
    assert trace.steps[2].count == 0
