"""Tests for what a retraction reaches.

Three properties: everything affected comes back with the chain that connects it to the
cause, the walk runs against the direction the dependency relations are written in, and
nothing is retracted -- the store is exactly as it was afterwards, because deciding a
conclusion is wrong is a judgement somebody records and not something a closure does.
"""

from __future__ import annotations

from atlas.steps.lineage import LineageOptions, lineage
from conftest import Fixture

OPTIONS = LineageOptions(follow=("derived_from", "used_dataset", "rests_on"))


def test_everything_standing_on_the_cause_comes_back_with_its_chain(science: Fixture) -> None:
    result = lineage({"store": science.store, "cause": science.nodes["archive"].id}, OPTIONS)

    reached = {one.node.id: one for one in result["affected"]}
    run = reached[science.nodes["run"].id]
    result_1 = reached[science.nodes["result-1"].id]
    assert run.direct
    assert run.through == ("used_dataset",)
    # The chain reads from the affected thing back to the cause.
    assert result_1.through == ("derived_from", "used_dataset")
    assert result_1.distance == 2


def test_the_cause_itself_is_not_among_what_it_affects(science: Fixture) -> None:
    result = lineage({"store": science.store, "cause": science.nodes["archive"].id}, OPTIONS)

    assert science.nodes["archive"].id not in {one.node.id for one in result["affected"]}


def test_the_closure_reaches_the_argument_that_rests_on_the_affected_result(
    science: Fixture,
) -> None:
    result = lineage({"store": science.store, "cause": science.nodes["archive"].id}, OPTIONS)

    assert science.nodes["line-for"].id in {one.node.id for one in result["affected"]}


def test_only_the_named_relations_are_followed(science: Fixture) -> None:
    narrow = lineage({"store": science.store, "cause": science.nodes["archive"].id},
                     LineageOptions(follow=("used_dataset",)))

    assert [one.node.id for one in narrow["affected"]] == [science.nodes["run"].id]


def test_the_direction_can_be_turned_round_for_a_pack_that_writes_them_the_other_way(
    science: Fixture,
) -> None:
    downstream = lineage({"store": science.store, "cause": science.nodes["result-1"].id},
                         LineageOptions(follow=("derived_from", "used_dataset"), upstream=False))

    # Following the relations the way they are written leads from a result to the
    # computation and the dataset behind it.
    assert {one.node.id for one in downstream["affected"]} == {
        science.nodes["run"].id, science.nodes["archive"].id
    }


def test_several_causes_are_closed_over_at_once(science: Fixture) -> None:
    result = lineage(
        {"store": science.store,
         "cause": (science.nodes["archive"].id, science.nodes["result-2"].id)},
        OPTIONS,
    )

    reached = {one.node.id for one in result["affected"]}
    assert science.nodes["line-for"].id in reached
    assert science.nodes["line-against"].id in reached


def test_a_budget_that_runs_out_is_reported(science: Fixture) -> None:
    result = lineage({"store": science.store, "cause": science.nodes["archive"].id},
                     LineageOptions(follow=OPTIONS.follow, limit=2))

    assert result["lineage_partial"]


def test_a_closure_retracts_nothing(science: Fixture) -> None:
    before = science.store.assertions()

    lineage({"store": science.store, "cause": science.nodes["archive"].id}, OPTIONS)

    assert science.store.assertions() == before
    assert science.store.get_node(science.nodes["result-1"].id) is not None


def test_a_cause_nothing_depends_on_affects_nothing(science: Fixture) -> None:
    result = lineage({"store": science.store, "cause": science.nodes["u1"].id}, OPTIONS)

    assert result["affected"] == ()
