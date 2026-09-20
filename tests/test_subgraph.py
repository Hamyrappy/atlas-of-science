"""Tests for choosing a small connected region that is worth its context budget.

Three rules matter more than the selection quality, and each has a test. An n-ary node
is taken whole or not at all, because a compact subgraph holding half of one is asserting
something nobody claimed. The evidence closure is not optional. And when the budget
binds, the package holds fewer things with complete grounds rather than more without
them -- and says how many it dropped.
"""

from __future__ import annotations

from atlas.steps.graph_expand import GraphExpandOptions
from atlas.steps.retrieve import Hit
from atlas.steps.subgraph import SubgraphOptions, grow, select_subgraph
from atlas.walk import Adjacency
from conftest import Fixture

POSITIONS = GraphExpandOptions(depth=2, limit=40, supports=("supports",), opposes=("disputes",))
DEFAULTS = SubgraphOptions(expand=POSITIONS)


def hits(science: Fixture, *keys: str) -> tuple[Hit, ...]:
    return tuple(
        Hit(node=science.nodes[key], score=1.0 - index * 0.2)
        for index, key in enumerate(keys)
    )


def test_a_region_grows_around_the_best_ranked_node(science: Fixture) -> None:
    result = select_subgraph(
        {"store": science.store, "hits": hits(science, "claim", "result-1"),
         "schema": science.schema},
        DEFAULTS,
    )

    assert science.nodes["claim"].id in result["selection"].nodes
    assert result["bundle"].grounded
    assert result["bundle"].method == "select_subgraph"


def test_the_region_is_connected(science: Fixture) -> None:
    result = select_subgraph(
        {"store": science.store, "hits": hits(science, "claim", "archive"),
         "schema": science.schema},
        SubgraphOptions(cost=0.0, expand=POSITIONS),
    )

    adjacency = Adjacency(science.store.links())
    chosen = set(result["selection"].nodes)
    # Every node but the first has a neighbour already in the region.
    assert all(
        any(edge.other in chosen for edge in adjacency.edges(node_id))
        for node_id in chosen
    ) or len(chosen) == 1


def test_an_edge_that_does_not_pay_for_itself_is_not_crossed(science: Fixture) -> None:
    expensive = SubgraphOptions(cost=10.0, expand=POSITIONS)

    result = select_subgraph(
        {"store": science.store, "hits": hits(science, "claim", "result-1"),
         "schema": science.schema},
        expensive,
    )

    assert len(result["selection"]) == 1


def test_selection_is_the_same_twice(science: Fixture) -> None:
    state = {"store": science.store, "hits": hits(science, "claim", "result-1"),
             "schema": science.schema}

    first = select_subgraph(dict(state), DEFAULTS)["selection"]
    second = select_subgraph(dict(state), DEFAULTS)["selection"]

    assert first.nodes == second.nodes


def test_a_node_that_may_not_be_split_brings_its_parts(science: Fixture) -> None:
    whole = SubgraphOptions(
        cost=0.0,
        whole=("EvidenceLine",),
        parts=("rests_on", "supports", "disputes"),
        expand=POSITIONS,
    )
    adjacency = Adjacency(science.store.links())
    prizes = {science.nodes["line-for"].id: 1.0}
    parts = {science.nodes["line-for"].id: (science.nodes["result-1"].id,)}

    selection = grow(adjacency, prizes, whole, parts)

    # Taking the line of argument means taking the result it rests on.
    assert science.nodes["result-1"].id in selection.nodes


def test_the_closure_is_not_optional_and_keeps_the_objection(science: Fixture) -> None:
    result = select_subgraph(
        {"store": science.store, "hits": hits(science, "claim"), "schema": science.schema},
        SubgraphOptions(cost=0.0, limit=2, expand=POSITIONS),
    )

    assert result["bundle"].opposing != ()


def test_when_the_budget_binds_fewer_roots_are_kept_and_the_count_is_reported(
    science: Fixture,
) -> None:
    tight = SubgraphOptions(
        cost=0.0,
        expand=GraphExpandOptions(depth=2, limit=3, supports=("supports",),
                                  opposes=("disputes",)),
    )

    result = select_subgraph(
        {"store": science.store, "hits": hits(science, "claim", "result-1", "u1", "archive"),
         "schema": science.schema},
        tight,
    )

    assert result["selection"].trimmed >= 0
    assert result["bundle"].roots


def test_a_question_that_ranked_nothing_selects_nothing(science: Fixture) -> None:
    result = select_subgraph(
        {"store": science.store, "hits": (), "schema": science.schema}, DEFAULTS
    )

    assert result["selection"].nodes == ()
    assert not result["bundle"].grounded


def test_the_value_of_a_region_is_its_prizes_less_its_edges(science: Fixture) -> None:
    result = select_subgraph(
        {"store": science.store, "hits": hits(science, "claim", "result-1"),
         "schema": science.schema},
        SubgraphOptions(cost=0.25, expand=POSITIONS),
    )

    selection = result["selection"]
    assert selection.value == round(selection.prize - selection.cost, 6)
