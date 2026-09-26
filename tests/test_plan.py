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
    with pytest.raises(ValueError, match="no class 'Hypothesis'"):
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
    assert "no node of this ontology matches those terms" in trace.steps[0].reason
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


def test_a_traversal_crosses_every_relation_the_ontology_makes_a_kind_of_it(
    science: Fixture,
) -> None:
    # bears_on has supports and disputes under it, so crossing it reaches the claim from
    # both lines, and the trace says which relations were actually asked for.
    trace = run(
        science.store,
        science.schema,
        options(
            Operator(op="resolve", type="EvidenceLine"),
            Operator(op="traverse", predicate="bears_on"),
        ),
    )

    assert trace.steps[1].nodes == (science.nodes["claim"].id,)
    assert len(trace.steps[1].witnesses) == 2
    assert {"supports(?x, ?y)", "disputes(?x, ?y)"} <= set(trace.steps[1].rewriting)


def test_resolving_a_class_also_finds_what_the_ontology_makes_one_by_its_relations(
    science: Fixture,
) -> None:
    from atlas.model import Agent, Assertion, Link, Node

    # A node recorded only as an entity, which a supporting line points at: the range of
    # `supports` makes it a proposition, and the QL rewriting of Proposition(?x) finds it.
    loose = Node(id="loose-claim-0001", type="Entity", fields={"name": "loose"},
                 spans=science.nodes["claim"].spans, schema_version=science.schema.version)
    link = Link.of(predicate="supports", src=science.nodes["line-for"].id, dst=loose.id,
                   spans=science.nodes["claim"].spans, schema_version=science.schema.version)
    agent = Agent(id="run", kind="run")
    for index, target in enumerate((loose, link)):
        science.store.assert_(Assertion(id=f"extra-{index}", agent=agent,
                                        at="2026-01-01T00:00:00+00:00", target=target))

    trace = run(science.store, science.schema, options(Operator(op="resolve", type="Proposition")))

    assert loose.id in trace.steps[0].nodes
    assert science.nodes["claim"].id in trace.steps[0].nodes
    assert any("supports(" in one for one in trace.steps[0].rewriting)
