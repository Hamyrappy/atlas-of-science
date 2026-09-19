"""Tests for the relational store: the same semantics as the others, plus the queries.

The first half is the protocol, and it is the protocol that matters -- a store that
answered `reach` beautifully and lost the append-only rule would be worse than useless.
So: nothing is ever removed from the log, a superseding assertion moves the projection
and not the history, and evidence for a source the store has never held is refused.

The second half is what this store exists for: a bounded neighbourhood computed in the
database, cycles that terminate, a budget that reports itself, and the query that finds
the objection a bounded walk would otherwise lose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.model import Agent, Assertion, Link, Node, Run, Schema, Segment, Source, Span
from atlas.store import open_store
from atlas.store.sqlite import SqliteStore

TEXT = "one two three four five six\n"
SOURCE = Source(id="s", origin="s.txt", segments=(Segment(number=1, text=TEXT),))
VERSION = "0" * 12
AGENT = Agent(id="run", kind="run")


def node(node_id: str, at: int = 0) -> Node:
    return Node(id=node_id, type="Thing", fields={"name": node_id},
                spans=(Span.of(SOURCE, 1, at, at + 3),), schema_version=VERSION)


def link(link_id: str, src: str, dst: str) -> Link:
    return Link(id=link_id, predicate="r", src=src, dst=dst,
                spans=(Span.of(SOURCE, 1, 0, 3),), schema_version=VERSION)


def asserted(target: Node | Link, at: str = "2026-01-01T00:00:00+00:00",
             supersedes: str | None = None, assertion_id: str = "") -> Assertion:
    return Assertion(id=assertion_id or f"a-{target.id}", agent=AGENT, at=at, target=target,
                     supersedes=supersedes)


@pytest.fixture
def store() -> SqliteStore:
    held = SqliteStore(None)
    held.add_source(SOURCE)
    return held


def test_a_source_goes_in_and_comes_back(store: SqliteStore) -> None:
    assert store.get_source("s") == SOURCE
    assert store.sources() == (SOURCE,)
    assert store.get_source("nothing") is None


def test_evidence_for_a_source_the_store_never_held_is_refused(store: SqliteStore) -> None:
    other = Source(id="elsewhere", origin="x", segments=(Segment(number=1, text=TEXT),))
    stray = Node(id="x" * 16, type="Thing", spans=(Span.of(other, 1, 0, 3),),
                 schema_version=VERSION)

    with pytest.raises(KeyError, match="unknown source"):
        store.assert_(asserted(stray))


def test_a_node_is_projected_and_found_by_id_and_by_type(store: SqliteStore) -> None:
    store.assert_(asserted(node("a" * 16)))

    assert store.get_node("a" * 16) is not None
    assert [one.id for one in store.by_type("Thing")] == ["a" * 16]
    assert store.get_nodes(["a" * 16, "missing"]) == (store.get_node("a" * 16),)


def test_superseding_moves_the_projection_and_never_the_log(store: SqliteStore) -> None:
    first = asserted(node("a" * 16), assertion_id="first")
    store.assert_(first)
    store.assert_(asserted(node("b" * 16, at=4), at="2026-01-02T00:00:00+00:00",
                           supersedes="first", assertion_id="second"))

    assert store.get_node("a" * 16) is None
    assert store.get_node("b" * 16) is not None
    # The history is whole: two assertions, and the first is still readable.
    assert len(store.assertions()) == 2
    assert store.assertions("a" * 16)[0].id == "first"


def test_re_asserting_the_same_id_keeps_the_later_one(store: SqliteStore) -> None:
    store.assert_(asserted(node("a" * 16), at="2026-01-02T00:00:00+00:00", assertion_id="late"))
    store.assert_(asserted(node("a" * 16), at="2026-01-01T00:00:00+00:00", assertion_id="early"))

    assert len(store.assertions("a" * 16)) == 2
    assert len(store.nodes()) == 1


def test_links_are_projected_beside_nodes(store: SqliteStore) -> None:
    store.assert_(asserted(node("a" * 16)))
    store.assert_(asserted(node("b" * 16, at=4)))
    store.assert_(asserted(link("l1", "a" * 16, "b" * 16)))

    assert [one.id for one in store.links()] == ["l1"]
    assert len(store.nodes()) == 2


def test_runs_and_schemas_are_kept(store: SqliteStore) -> None:
    store.add_run(Run(id="r1", at="2026-01-01T00:00:00+00:00"))
    store.add_schema(Schema(version=VERSION))
    store.add_schema(Schema(version=VERSION))

    assert [one.id for one in store.runs()] == ["r1"]
    assert store.get_schema(VERSION) is not None
    assert store.get_schema("nope") is None


def chain(store: SqliteStore, length: int) -> list[str]:
    """A -> B -> C ... as long as asked, all in the store."""
    ids = [chr(ord("a") + n) * 16 for n in range(length)]
    for index, node_id in enumerate(ids):
        store.assert_(asserted(node(node_id, at=index)))
    for index, (src, dst) in enumerate(zip(ids, ids[1:], strict=False)):
        store.assert_(asserted(link(f"l{index}", src, dst)))
    return ids


def test_reach_returns_the_neighbourhood_with_its_distances(store: SqliteStore) -> None:
    ids = chain(store, 4)

    found = store.reach([ids[0]], depth=2)

    assert found.distances == {ids[0]: 0, ids[1]: 1, ids[2]: 2}
    assert not found.partial


def test_reach_walks_both_ways_because_a_question_is_not_directed(store: SqliteStore) -> None:
    ids = chain(store, 3)

    found = store.reach([ids[2]], depth=2)

    assert set(found.distances) == set(ids)


def test_a_cycle_terminates(store: SqliteStore) -> None:
    ids = chain(store, 3)
    store.assert_(asserted(link("loop", ids[2], ids[0])))

    found = store.reach([ids[0]], depth=5)

    assert set(found.distances) == set(ids)


def test_a_budget_that_binds_is_reported(store: SqliteStore) -> None:
    ids = chain(store, 5)

    found = store.reach([ids[0]], depth=4, limit=2)

    assert len(found.distances) == 2
    assert found.partial


def test_reach_with_no_seeds_finds_nothing(store: SqliteStore) -> None:
    chain(store, 3)

    assert store.reach([]).distances == {}


def test_links_among_takes_only_the_ones_with_both_ends_inside(store: SqliteStore) -> None:
    ids = chain(store, 3)

    inside = store.links_among(ids[:2])

    assert [one.id for one in inside] == ["l0"]


def test_links_touching_finds_the_relation_a_bounded_walk_would_lose(
    store: SqliteStore,
) -> None:
    ids = chain(store, 3)
    store.assert_(asserted(
        Link(id="against", predicate="disputes", src=ids[2], dst=ids[0],
             spans=(Span.of(SOURCE, 1, 0, 3),), schema_version=VERSION)
    ))

    # Only the first node is in play, and the objection runs to it from outside.
    found = store.links_touching([ids[0]], ("disputes",))

    assert [one.id for one in found] == ["against"]


def test_a_store_on_disk_is_opened_by_name_and_says_where_it_lives(tmp_path: Path) -> None:
    opened = open_store({"sqlite": {"path": "atlas.db"}}, tmp_path)

    assert opened.location == tmp_path / "atlas.db"
    assert opened.artifact("index.json") == tmp_path / "index.json"


def test_a_store_in_memory_has_nowhere_to_put_a_derived_file() -> None:
    assert open_store("sqlite").artifact("index.json") is None
