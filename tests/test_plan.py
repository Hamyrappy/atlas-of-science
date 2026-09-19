"""Tests for the plan of typed graph operations, and the three rules it enforces.

A plan is type-checked before it runs, which is the defence against a planner replacing
an unknown relation with a plausible word. An operator with no data says so and the plan
continues, so the trace names the step that emptied it. And an aggregate counts the whole
selected set rather than a ranked sample.
"""

from __future__ import annotations

import pytest

from atlas.steps.graph_expand import GraphExpandOptions
from atlas.steps.plan import Operator, PlanOptions, check, execute_plan, run
from conftest import Fixture

POSITIONS = GraphExpandOptions(depth=2, limit=60, supports=("supports",), opposes=("disputes",))


def options(*plan: Operator, **over) -> PlanOptions:
    return PlanOptions(plan=plan, expand=POSITIONS, **over)


def state(science: Fixture) -> dict:
    return {"store": science.store, "schema": science.schema}


def test_a_plan_resolves_traverses_and_packages_what_it_selected(science: Fixture) -> None:
    result = execute_plan(
        state(science),
        options(
            Operator(op="resolve", type="Proposition"),
            Operator(op="traverse", predicate="supports", forward=False),
        ),
    )

    assert result["bundle"].grounded
    assert result["bundle"].method == "execute_plan"
    assert science.nodes["line-for"].id in result["bundle"].roots


def test_a_relation_the_pack_does_not_declare_stops_the_plan_before_it_runs(
    science: Fixture,
) -> None:
    with pytest.raises(ValueError, match="no relation 'corroborates'"):
        execute_plan(state(science), options(Operator(op="traverse", predicate="corroborates")))


def test_a_type_the_pack_does_not_know_stops_the_plan(science: Fixture) -> None:
    with pytest.raises(ValueError, match="no type 'Hypothesis'"):
        execute_plan(state(science), options(Operator(op="resolve", type="Hypothesis")))


def test_every_problem_with_a_plan_is_named_at_once(science: Fixture) -> None:
    problems = check(
        (Operator(op="traverse"), Operator(op="filter"), Operator(op="resolve", type="Nope")),
        science.schema,
    )

    assert len(problems) == 3
    assert "needs a relation to cross" in problems[0]
    assert "needs a field to filter on" in problems[1]


def test_a_step_that_reached_nothing_says_so_and_the_plan_continues(
    science: Fixture,
) -> None:
    trace = run(
        science.store,
        science.schema,
        options(
            Operator(op="resolve", type="Proposition", terms=("nothing-like-this",)),
            Operator(op="traverse", predicate="supports"),
        ),
    )

    assert len(trace) == 2
    assert trace.emptied_at is not None
    assert trace.emptied_at.operator.op == "resolve"
    assert "no node of this pack matches those terms" in trace.steps[0].reason
    assert "nothing reached this step" in trace.steps[1].reason


def test_a_traversal_keeps_the_links_it_crossed(science: Fixture) -> None:
    trace = run(
        science.store,
        science.schema,
        options(
            Operator(op="resolve", type="Proposition"),
            Operator(op="traverse", predicate="supports", forward=False),
        ),
    )

    assert trace.steps[1].witnesses


def test_an_aggregate_counts_the_whole_selected_set(science: Fixture) -> None:
    result = execute_plan(
        state(science),
        options(
            Operator(op="resolve", type="StudyResult"),
            Operator(op="aggregate"),
        ),
    )

    assert result["answer_count"] == 2


def test_a_filter_narrows_by_a_field(science: Fixture) -> None:
    trace = run(
        science.store,
        science.schema,
        options(
            Operator(op="resolve", type="StudyResult"),
            Operator(op="filter", field="value", value="0.94"),
        ),
    )

    assert trace.steps[1].nodes == (science.nodes["result-1"].id,)


def test_a_filter_with_no_value_asks_only_that_the_field_is_filled(science: Fixture) -> None:
    trace = run(
        science.store,
        science.schema,
        options(
            Operator(op="resolve", type="StudyResult"),
            Operator(op="filter", field="value"),
        ),
    )

    assert len(trace.steps[1]) == 2


def test_compare_groups_by_what_a_field_says(science: Fixture) -> None:
    trace = run(
        science.store,
        science.schema,
        options(
            Operator(op="resolve", type="Context"),
            Operator(op="compare", field="conditions"),
        ),
    )

    assert set(trace.steps[1].groups) == {"u1", "u2"}


def test_a_budget_that_bound_is_reported_rather_than_silently_answered(
    science: Fixture,
) -> None:
    trace = run(
        science.store,
        science.schema,
        options(Operator(op="resolve"), limit=2),
    )

    assert trace.partial
    assert "more than the budget allows" in trace.steps[0].reason


def test_the_package_says_which_operator_selected_each_thing(science: Fixture) -> None:
    result = execute_plan(
        state(science),
        options(Operator(op="resolve", type="Proposition")),
    )

    reasons = set(result["bundle"].reasons.values())
    assert any("selected by resolve" in reason for reason in reasons)
