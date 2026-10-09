"""Tests for letting relevance spread, and for the three rules that keep it from being truth.

Direction does not become weight -- a disputing relation carries the weight its predicate
was given, and which side it is on is applied by the evidence closure afterwards. A score
comes back with the walk that explains it, so a hub with no route to show can be told
apart from a finding. And the ranking settles to the same numbers twice.
"""

from __future__ import annotations

from atlas.steps.diffuse import DiffuseOptions, diffuse, pagerank
from atlas.steps.graph_expand import GraphExpandOptions
from atlas.steps.retrieve import Hit
from atlas.walk import Adjacency
from conftest import Fixture

POSITIONS = GraphExpandOptions(depth=2, limit=40, supports=("supports",), opposes=("disputes",))
DEFAULTS = DiffuseOptions(expand=POSITIONS)


def hits(science: Fixture, *keys: str) -> tuple[Hit, ...]:
    return tuple(Hit(node=science.nodes[key], score=1.0) for key in keys)


def test_diffusion_reaches_what_no_single_short_walk_would_rank(science: Fixture) -> None:
    result = diffuse(
        {"store": science.store, "hits": hits(science, "archive"), "schema": science.schema},
        DEFAULTS,
    )

    reached = {one.node_id for one in result["ranked"]}
    assert science.nodes["result-1"].id in reached
    assert result["bundle"].method == "diffuse"


def test_a_score_comes_back_with_the_walk_that_explains_it(science: Fixture) -> None:
    result = diffuse(
        {"store": science.store, "hits": hits(science, "claim"), "schema": science.schema},
        DEFAULTS,
    )

    explained = [one for one in result["ranked"] if one.explained]
    assert explained
    assert explained[0].walk.nodes[0] == science.nodes["claim"].id


def test_direction_does_not_become_weight(science: Fixture) -> None:
    adjacency = Adjacency(science.store.links())
    seeds = {science.nodes["claim"].id: 1.0}

    plain = pagerank(adjacency, seeds)

    # Every score is a share of one unit of attention, so nothing is negative however a
    # relation is meant.
    assert all(score >= 0 for score in plain.values())
    assert abs(sum(plain.values()) - 1.0) < 1e-6


def test_the_side_a_relation_is_on_is_applied_by_the_closure(science: Fixture) -> None:
    result = diffuse(
        {"store": science.store, "hits": hits(science, "claim"), "schema": science.schema},
        DEFAULTS,
    )

    assert result["bundle"].opposing != ()
    assert result["bundle"].supporting != ()


def test_a_relation_weighted_down_carries_less(science: Fixture) -> None:
    adjacency = Adjacency(science.store.links())
    seeds = {science.nodes["claim"].id: 1.0}

    even = pagerank(adjacency, seeds)
    damped = pagerank(adjacency, seeds, by_predicate={"disputes": 0.01})

    against = science.nodes["line-against"].id
    assert damped[against] < even[against]


def test_the_ranking_settles_to_the_same_numbers_twice(science: Fixture) -> None:
    adjacency = Adjacency(science.store.links())
    seeds = {science.nodes["claim"].id: 1.0}

    assert pagerank(adjacency, seeds) == pagerank(adjacency, seeds)


def test_a_question_with_no_seeds_ranks_nothing(science: Fixture) -> None:
    assert pagerank(Adjacency(science.store.links()), {}) == {}


def test_a_graph_with_no_relations_ranks_nothing() -> None:
    assert pagerank(Adjacency([]), {"a": 1.0}) == {}


def test_the_package_says_when_a_node_had_no_route_from_a_seed(science: Fixture) -> None:
    result = diffuse(
        {"store": science.store, "hits": hits(science, "claim"), "schema": science.schema},
        DiffuseOptions(depth=1, limit=12, expand=POSITIONS),
    )

    reasons = " ".join(result["bundle"].reasons.values())
    assert "diffusion" in reasons
