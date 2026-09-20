"""Tests for the partition and the report that is never evidence.

The two decisions the module makes are the two under test. A report is derived text, not
a node -- there is nothing in it a reader could cite, which is enforced by the report
never entering the graph at all. And the partition is reproducible and does not collapse:
two cliques joined by one edge come apart, which is the least a partition has to do to be
worth computing.
"""

from __future__ import annotations

from atlas.model import Link, Node, Segment, Source, Span
from atlas.steps.communities import CommunitiesOptions, communities, partition
from atlas.walk import Adjacency
from conftest import Fixture

DEFAULTS = CommunitiesOptions()
TEXT = "a b c d e f\n"
SOURCE = Source(id="s", origin="s.txt", segments=(Segment(number=1, text=TEXT),))


def built(science: Fixture, options: CommunitiesOptions = DEFAULTS):
    return communities({"store": science.store, "schema": science.schema}, options)


def test_every_projected_node_of_a_group_is_in_it(science: Fixture) -> None:
    found = built(science)["communities"]

    members = {node_id for community in found for node_id in community.members}
    assert members <= {node.id for node in science.store.nodes()}
    assert found


def test_a_community_carries_the_kinds_it_holds_and_its_share_of_the_corpus(
    science: Fixture,
) -> None:
    found = built(science)["communities"]

    biggest = found[0]
    assert biggest.kinds
    assert 0 < biggest.coverage <= 1.0
    assert len(biggest) == len(biggest.members)


def test_a_report_is_prose_about_nodes_and_is_not_one(science: Fixture) -> None:
    found = built(science)["communities"]

    report = found[0].report
    assert report
    assert not isinstance(report, Node)
    # Nothing in the store gained a node for it, so nothing can cite it.
    assert len(science.store.nodes()) == len(science.nodes)


def test_communities_are_rebuilt_and_never_asserted(science: Fixture) -> None:
    before = science.store.assertions()

    built(science)

    assert science.store.assertions() == before


def test_the_partition_is_the_same_twice(science: Fixture) -> None:
    first = built(science)["communities"]
    second = built(science)["communities"]

    assert [one.members for one in first] == [one.members for one in second]


def test_a_group_smaller_than_asked_for_is_left_out(science: Fixture) -> None:
    found = built(science, CommunitiesOptions(min_size=99))["communities"]

    assert found == ()


def test_only_the_named_relations_hold_a_community_together(science: Fixture) -> None:
    narrow = built(science, CommunitiesOptions(follow=("comparable_with",)))["communities"]

    [one] = narrow
    assert one.kinds == ("Context",)


def link(link_id: str, src: str, dst: str) -> Link:
    return Link(id=link_id, predicate="r", src=src, dst=dst,
                spans=(Span.of(SOURCE, 1, 0, 1),), schema_version="0" * 12)


def test_two_cliques_joined_by_one_edge_come_apart() -> None:
    edges = [
        link("1", "a", "b"), link("2", "b", "c"), link("3", "a", "c"),
        link("4", "d", "e"), link("5", "e", "f"), link("6", "d", "f"),
        link("7", "c", "d"),
    ]

    labels = partition(Adjacency(edges))

    assert len({labels[one] for one in "abc"}) == 1
    assert len({labels[one] for one in "def"}) == 1
    assert labels["a"] != labels["f"]


def test_a_graph_with_no_edges_leaves_every_node_on_its_own() -> None:
    assert partition(Adjacency([])) == {}


def test_agglomeration_stops_on_the_modularity_rather_than_on_the_cap() -> None:
    edges = [link("1", "a", "b"), link("2", "b", "c")]

    assert partition(Adjacency(edges), rounds=1) == partition(Adjacency(edges), rounds=8)
