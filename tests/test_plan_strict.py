"""Strict operator contracts for generated plans; the static baseline remains available."""

from __future__ import annotations

import pytest

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
    ((Operator(op="resolve"),), "needs a declared class"),
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


def test_unimplemented_strict_operators_are_operator_gaps(science: Fixture):
    with pytest.raises(PlanRefused) as caught:
        run(science.store, science.schema, options(
            Operator(op="resolve", type="StudyResult"),
            Operator(op="join", predicate="observed_under"),
        ))
    assert caught.value.category == "operator"


def test_a_strict_execution_does_not_assert_anything(science: Fixture):
    before = tuple(science.store.assertions())
    execute_plan({"store": science.store, "schema": science.schema}, options(
        Operator(op="resolve", type="StudyResult"), Operator(op="aggregate"),
    ))
    assert tuple(science.store.assertions()) == before
