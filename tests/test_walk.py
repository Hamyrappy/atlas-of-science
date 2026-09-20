"""Tests for the graph primitives every architecture that walks a graph is built on.

Three claims are under test, and they are the three the module promises: a link is
walked in both directions and remembers which way it was asserted, the order a walk
visits things in comes from the data and not from a dictionary, and a budget that runs
out is reported rather than filled in.
"""

from __future__ import annotations

import pytest

from atlas.model import Link, Segment, Source, Span
from atlas.walk import Adjacency, Walk, components, reach, walks, weights

TEXT = "a b c d e f g h\n"
SOURCE = Source(id="s", origin="s.txt", segments=(Segment(number=1, text=TEXT),))
VERSION = "0" * 12


def link(predicate: str, src: str, dst: str, at: int = 0) -> Link:
    return Link.of(
        predicate=predicate,
        src=src,
        dst=dst,
        spans=(Span.of(SOURCE, 1, at, at + 3),),
        schema_version=VERSION,
    )


@pytest.fixture
def chain() -> Adjacency:
    """A -> B -> C, plus a D hanging off B by another relation, and an island E."""
    return Adjacency(
        [link("r", "A", "B"), link("r", "B", "C", 2), link("q", "B", "D", 4),
         link("r", "E", "E", 6)]
    )


def test_a_link_is_walked_in_both_directions(chain: Adjacency) -> None:
    assert {edge.other for edge in chain.edges("B")} == {"A", "C", "D"}
    assert {edge.other for edge in chain.edges("B", backward=False)} == {"C", "D"}
    assert {edge.other for edge in chain.edges("B", forward=False)} == {"A"}


def test_a_walk_remembers_which_way_each_link_was_asserted(chain: Adjacency) -> None:
    [found] = walks(chain, "C", "A", depth=3)

    assert found.nodes == ("C", "B", "A")
    # Both links were asserted the other way round, and the walk says so rather than
    # presenting itself as "C relates to B relates to A".
    assert found.forward == (False, False)
    assert found.predicates == ("r", "r")


def test_reach_returns_the_shortest_walk_to_every_node_within_depth(chain: Adjacency) -> None:
    found = reach(chain, ["A"], depth=2)

    assert set(found.nodes) == {"A", "B", "C", "D"}
    assert found.walks["A"] == Walk(nodes=("A",))
    assert found.walks["D"].length == 2
    assert not found.partial


def test_depth_bounds_the_reach_without_calling_it_partial(chain: Adjacency) -> None:
    found = reach(chain, ["A"], depth=1)

    assert set(found.nodes) == {"A", "B"}
    # The frontier is not exhausted, but the caller asked for one hop and got one hop.
    assert not found.partial


def test_a_budget_that_runs_out_says_so(chain: Adjacency) -> None:
    found = reach(chain, ["A"], depth=3, limit=2)

    assert len(found) == 2
    assert found.partial


def test_a_restricted_adjacency_drops_the_relations_it_was_not_given() -> None:
    restricted = Adjacency.of([link("r", "A", "B"), link("q", "B", "D", 4)], follow=("r",))

    assert {edge.other for edge in restricted.edges("B")} == {"A"}
    assert len(restricted) == 1


def test_paths_are_simple_shortest_first_and_ordered_by_the_links_they_cross() -> None:
    #  A -> B -> C and a longer way round through D.
    adjacency = Adjacency(
        [link("r", "A", "B"), link("r", "B", "C", 2),
         link("r", "A", "D", 4), link("r", "D", "C", 6)]
    )

    found = walks(adjacency, "A", "C", depth=3)

    assert [one.length for one in found] == [2, 2]
    assert all(len(set(one.nodes)) == len(one.nodes) for one in found)
    assert found == tuple(sorted(found, key=lambda one: (one.length, one.links)))


def test_a_node_reaches_itself_by_a_walk_of_no_links(chain: Adjacency) -> None:
    assert walks(chain, "A", "A") == (Walk(nodes=("A",)),)


def test_components_are_ordered_by_size_then_by_smallest_id(chain: Adjacency) -> None:
    assert components(chain) == (frozenset({"A", "B", "C", "D"}), frozenset({"E"}))


def test_weights_default_to_one_and_take_the_table_where_it_names_a_relation(
    chain: Adjacency,
) -> None:
    table = weights(chain, {"q": 0.25})

    by_predicate = {chain.links[link_id].predicate: value for link_id, value in table.items()}
    assert by_predicate == {"r": 1.0, "q": 0.25}
