"""Tests for returning the chains that explain a connection, and keeping the counter-path.

The two rules that decide whether pruning is safe are the two under test. Redundancy is
judged by content, so two readings of one chain are one path and two chains over
different studies are two. And a path crossing a relation the configuration calls
opposing is kept whatever it scored -- because it is rare by nature and scores badly by
construction, and losing it would make a pruned search more confident than an unpruned
one.
"""

from __future__ import annotations

from atlas.steps.graph_expand import GraphExpandOptions
from atlas.steps.paths import Path, SelectPathsOptions, enumerate_paths, flow, prune, select_paths
from atlas.steps.retrieve import Hit
from atlas.walk import Adjacency, Walk, walks
from conftest import Fixture

POSITIONS = GraphExpandOptions(depth=3, limit=60, supports=("supports",), opposes=("disputes",))
DEFAULTS = SelectPathsOptions(expand=POSITIONS)


def hits(science: Fixture, *keys: str) -> tuple[Hit, ...]:
    return tuple(Hit(node=science.nodes[key], score=1.0) for key in keys)


def test_the_chains_between_two_named_things_come_back_ordered(science: Fixture) -> None:
    result = select_paths(
        {"store": science.store, "hits": hits(science, "result-1", "claim"),
         "schema": science.schema},
        DEFAULTS,
    )

    found = result["paths"]
    assert found
    assert [one.score for one in found] == sorted((one.score for one in found), reverse=True)
    assert result["bundle"].method == "select_paths"


def test_a_shorter_chain_outranks_a_longer_one(science: Fixture) -> None:
    adjacency = Adjacency(science.store.links())
    short = walks(adjacency, science.nodes["line-for"].id, science.nodes["claim"].id,
                  depth=1, limit=1)[0]
    long = walks(adjacency, science.nodes["result-1"].id, science.nodes["claim"].id,
                 depth=3, limit=1)[0]

    assert flow(short, {}, 0.8) > flow(long, {}, 0.8)


def test_two_readings_of_one_chain_are_one_path(science: Fixture) -> None:
    adjacency = Adjacency(science.store.links())
    [walk] = walks(adjacency, science.nodes["line-for"].id, science.nodes["claim"].id,
                   depth=1, limit=1)
    twice = (Path(walk=walk, score=0.8), Path(walk=walk, score=0.8))

    assert len(prune(twice, 8, (), adjacency)) == 1


def test_two_chains_over_different_things_are_two_paths(science: Fixture) -> None:
    adjacency = Adjacency(science.store.links())
    one = walks(adjacency, science.nodes["line-for"].id, science.nodes["claim"].id,
                depth=1, limit=1)[0]
    other = walks(adjacency, science.nodes["line-against"].id, science.nodes["claim"].id,
                  depth=1, limit=1)[0]

    kept = prune((Path(walk=one, score=0.8), Path(walk=other, score=0.8)), 8, (), adjacency)

    assert len(kept) == 2


def test_a_counter_path_the_budget_dropped_is_put_back(science: Fixture) -> None:
    adjacency = Adjacency(science.store.links())
    supporting = walks(adjacency, science.nodes["line-for"].id, science.nodes["claim"].id,
                       depth=1, limit=1)[0]
    opposing = walks(adjacency, science.nodes["line-against"].id, science.nodes["claim"].id,
                     depth=1, limit=1)[0]
    scored = (Path(walk=supporting, score=0.9), Path(walk=opposing, score=0.1))

    # Room for one, and the one that fits is the supporting chain.
    kept = prune(scored, 1, ("disputes",), adjacency)

    assert len(kept) == 2
    assert "kept as a counter-path" in kept[1].reason


def test_with_nothing_named_as_opposing_nothing_is_rescued(science: Fixture) -> None:
    adjacency = Adjacency(science.store.links())
    one = walks(adjacency, science.nodes["line-for"].id, science.nodes["claim"].id,
                depth=1, limit=1)[0]
    other = walks(adjacency, science.nodes["line-against"].id, science.nodes["claim"].id,
                  depth=1, limit=1)[0]

    kept = prune((Path(walk=one, score=0.9), Path(walk=other, score=0.1)), 1, (), adjacency)

    assert len(kept) == 1


def test_a_signature_is_the_things_crossed_in_order() -> None:
    path = Path(walk=Walk(nodes=("a", "b"), links=("l",), predicates=("r",), forward=(True,)),
                score=1.0)

    assert path.signature == ("a", "r", "b")


def test_enumeration_is_bounded_by_depth(science: Fixture) -> None:
    adjacency = Adjacency(science.store.links())

    found = enumerate_paths(
        adjacency,
        (science.nodes["archive"].id, science.nodes["claim"].id),
        SelectPathsOptions(depth=2, expand=POSITIONS),
    )

    assert all(path.walk.length <= 2 for path in found)


def test_a_question_naming_one_thing_finds_no_chain_and_still_packages_it(
    science: Fixture,
) -> None:
    result = select_paths(
        {"store": science.store, "hits": hits(science, "claim"), "schema": science.schema},
        DEFAULTS,
    )

    assert result["paths"] == ()
    # The root is still packaged, so the answer is about something rather than nothing.
    assert result["bundle"].roots == (science.nodes["claim"].id,)
