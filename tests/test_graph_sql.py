"""Tests for building the evidence package out of queries instead of out of a scan.

The package that comes back has to be the same object with the same guarantees, however
the graph arrived -- so the first test is that the relational route and the in-process
route agree on the same store. The rest are the two things the relational route has to
get right on its own: a store that cannot answer the queries is told so rather than
quietly given the other route, and an objection outside the fetched neighbourhood is
found by a second query rather than lost to the budget.
"""

from __future__ import annotations

import pytest

from atlas.model import Agent, Assertion, Link, Node, Segment, Source, Span
from atlas.steps.graph_expand import GraphExpandOptions, graph_expand
from atlas.steps.graph_sql import graph_expand_sql
from atlas.steps.retrieve import Hit
from atlas.store.memory import MemoryStore
from atlas.store.sqlite import SqliteStore

TEXT = "one two three four five six seven\n"
SOURCE = Source(id="s", origin="s.txt", segments=(Segment(number=1, text=TEXT),))
VERSION = "0" * 12
AGENT = Agent(id="run", kind="run")
POSITIONS = GraphExpandOptions(depth=2, limit=20, supports=("supports",),
                               opposes=("disputes",))


def node(node_id: str, at: int = 0) -> Node:
    return Node(id=node_id, type="Thing", fields={"name": node_id},
                spans=(Span.of(SOURCE, 1, at, at + 3),), schema_version=VERSION)


def link(link_id: str, predicate: str, src: str, dst: str) -> Link:
    return Link(id=link_id, predicate=predicate, src=src, dst=dst,
                spans=(Span.of(SOURCE, 1, 0, 3),), schema_version=VERSION)


#: A claim with a supporting line two hops away, and an objection reaching it from a
#: node the walk does not pass through.
NODES = [node("claim" + "0" * 11), node("for" + "0" * 13, 4), node("result" + "0" * 10, 8),
         node("against" + "0" * 9, 12)]
LINKS = [
    link("l1", "supports", "for" + "0" * 13, "claim" + "0" * 11),
    link("l2", "rests_on", "for" + "0" * 13, "result" + "0" * 10),
    link("l3", "disputes", "against" + "0" * 9, "claim" + "0" * 11),
]


def fill(store: MemoryStore | SqliteStore) -> None:
    store.add_source(SOURCE)
    for index, target in enumerate([*NODES, *LINKS]):
        store.assert_(Assertion(id=f"a{index}", agent=AGENT,
                                at="2026-01-01T00:00:00+00:00", target=target))


@pytest.fixture
def relational() -> SqliteStore:
    store = SqliteStore(None)
    fill(store)
    return store


@pytest.fixture
def in_process() -> MemoryStore:
    store = MemoryStore()
    fill(store)
    return store


def hits(store) -> tuple[Hit, ...]:
    root = store.get_node(NODES[0].id)
    return (Hit(node=root, score=0.5),)


def test_the_two_routes_agree_on_the_same_store(
    relational: SqliteStore, in_process: MemoryStore
) -> None:
    by_query = graph_expand_sql({"store": relational, "hits": hits(relational)}, POSITIONS)
    by_scan = graph_expand({"store": in_process, "hits": hits(in_process)}, POSITIONS)

    assert {one.id for one in by_query["bundle"].nodes} == {
        one.id for one in by_scan["bundle"].nodes
    }
    assert {one.id for one in by_query["bundle"].links} == {
        one.id for one in by_scan["bundle"].links
    }
    assert by_query["bundle"].opposing == by_scan["bundle"].opposing


def test_the_package_says_which_route_built_it(relational: SqliteStore) -> None:
    bundle = graph_expand_sql({"store": relational, "hits": hits(relational)},
                              POSITIONS)["bundle"]

    assert bundle.method == "graph_expand_sql"
    assert bundle.grounded


def test_a_store_that_cannot_answer_the_queries_is_told_so(in_process: MemoryStore) -> None:
    with pytest.raises(ValueError, match="cannot answer a bounded neighbourhood"):
        graph_expand_sql({"store": in_process, "hits": hits(in_process)}, POSITIONS)


def test_an_objection_outside_the_fetched_neighbourhood_is_still_found(
    relational: SqliteStore,
) -> None:
    # One hop only, so the walk never reaches the node the objection comes from.
    tight = GraphExpandOptions(depth=1, limit=2, opposes=("disputes",))

    bundle = graph_expand_sql({"store": relational, "hits": hits(relational)}, tight)["bundle"]

    assert "l3" in bundle.opposing
    assert any(one.id == "against" + "0" * 9 for one in bundle.nodes)


def test_a_neighbourhood_the_budget_bound_is_reported_partial(
    relational: SqliteStore,
) -> None:
    bundle = graph_expand_sql(
        {"store": relational, "hits": hits(relational)},
        GraphExpandOptions(depth=2, limit=1),
    )["bundle"]

    assert bundle.partial


def test_only_the_named_relations_are_followed(relational: SqliteStore) -> None:
    bundle = graph_expand_sql(
        {"store": relational, "hits": hits(relational)},
        GraphExpandOptions(depth=2, limit=20, follow=("supports",)),
    )["bundle"]

    assert {one.predicate for one in bundle.links} == {"supports"}
