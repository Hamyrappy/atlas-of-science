"""Tests for the store: the same body run against both implementations.

What is under test is the semantics, not the medium -- a read returns the current
claim, a write never destroys the claim it replaces -- so the fixture is
parametrised and every test but the one about reopening a file is medium-blind.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from atlas.model import Agent, Assertion, Link, Node, Segment, Source, Span
from atlas.store import Store
from atlas.store.jsonl import JsonlStore
from atlas.store.memory import MemoryStore

TEXT = "The task is to segment cells.\nWe introduce a model.\n"
SOURCE = Source(
    id="src-000000001", origin="corpus/paper.pdf", segments=(Segment(number=1, text=TEXT),)
)
VERSION = "0" * 12
HUMAN = Agent(id="agent-h", kind="human", label="reviewer")
MODEL = Agent(id="agent-m", kind="model", label="extractor")


def span(quote: str = "segment cells") -> Span:
    start = TEXT.index(quote)
    return Span.of(SOURCE, 1, start, start + len(quote))


def node(node_id: str = "node-1", type_name: str = "Method", **fields: str) -> Node:
    return Node(
        id=node_id, type=type_name, spans=(span(),), schema_version=VERSION, fields=fields
    )


def asserted(
    assertion_id: str,
    target: Node | Link,
    at: str,
    agent: Agent = MODEL,
    supersedes: str | None = None,
) -> Assertion:
    return Assertion(id=assertion_id, agent=agent, at=at, target=target, supersedes=supersedes)


@pytest.fixture(params=["memory", "jsonl"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Store]:
    made = MemoryStore() if request.param == "memory" else JsonlStore(tmp_path / "atlas")
    made.add_source(SOURCE)
    yield made


def test_an_empty_store_projects_to_nothing(store: Store) -> None:
    assert store.nodes() == ()
    assert store.links() == ()
    assert store.assertions() == ()


def test_a_source_comes_back_as_it_went_in(store: Store) -> None:
    assert store.get_source(SOURCE.id) == SOURCE
    assert store.get_source("src-unknown") is None


def test_evidence_must_stand_on_a_source_the_store_holds(store: Store) -> None:
    stray = Span(source_id="src-elsewhere", segment=1, start=0, end=4, text="task")
    orphan = Node(id="node-9", type="Method", spans=(stray,), schema_version=VERSION)

    with pytest.raises(KeyError, match="unknown source"):
        store.assert_(asserted("a-9", orphan, at="2026-01-01T00:00:00Z"))


def test_a_superseding_assertion_replaces_its_target_and_keeps_the_history(store: Store) -> None:
    store.assert_(asserted("a-1", node(name="segmentation"), at="2026-01-01T00:00:00Z"))
    store.assert_(
        asserted(
            "a-2",
            node(name="cell segmentation"),
            at="2026-01-02T00:00:00Z",
            agent=HUMAN,
            supersedes="a-1",
        )
    )

    assert [n.fields["name"] for n in store.nodes()] == ["cell segmentation"]
    assert [a.id for a in store.assertions()] == ["a-1", "a-2"]
    assert [a.agent.kind for a in store.assertions("node-1")] == ["model", "human"]


def test_two_agents_asserting_about_one_node_do_not_overwrite_each_other(store: Store) -> None:
    store.assert_(asserted("a-1", node(name="from the model"), at="2026-01-01T00:00:00Z"))
    store.assert_(
        asserted("a-2", node(name="from the reviewer"), at="2026-01-02T00:00:00Z", agent=HUMAN)
    )

    assert [n.fields["name"] for n in store.nodes()] == ["from the reviewer"]
    assert [(a.id, a.agent.id) for a in store.assertions("node-1")] == [
        ("a-1", MODEL.id),
        ("a-2", HUMAN.id),
    ]


def test_nodes_and_links_project_side_by_side(store: Store) -> None:
    link = Link.of("uses", "node-1", "node-2", (span(),), VERSION)
    store.assert_(asserted("a-1", node("node-1"), at="2026-01-01T00:00:00Z"))
    store.assert_(asserted("a-2", node("node-2", "Dataset"), at="2026-01-01T00:00:01Z"))
    store.assert_(asserted("a-3", link, at="2026-01-01T00:00:02Z"))

    assert [n.id for n in store.nodes()] == ["node-1", "node-2"]
    assert [(one.src, one.predicate, one.dst) for one in store.links()] == [
        ("node-1", "uses", "node-2")
    ]
    assert [n.id for n in store.by_type("Dataset")] == ["node-2"]
    assert store.by_type("Method") == (store.nodes()[0],)
    assert store.by_type("ex:Dataset") == ()


def test_reopening_a_jsonl_store_recovers_the_same_projection(tmp_path: Path) -> None:
    written = JsonlStore(tmp_path / "atlas")
    written.add_source(SOURCE)
    written.assert_(asserted("a-1", node(name="first"), at="2026-01-01T00:00:00Z"))
    written.assert_(
        asserted("a-2", node(name="second"), at="2026-01-02T00:00:00Z", supersedes="a-1")
    )

    reopened = JsonlStore(tmp_path / "atlas")

    assert reopened.get_source(SOURCE.id) == SOURCE
    assert reopened.nodes() == written.nodes()
    assert reopened.assertions() == written.assertions()
    assert (tmp_path / "atlas" / "assertions.jsonl").read_text(encoding="utf-8").count("\n") == 2
