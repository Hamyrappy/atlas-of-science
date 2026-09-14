"""Tests for the store: the same body run against both implementations.

What is under test is the semantics, not the medium -- a read returns the current
claim, a write never destroys the claim it replaces -- so the fixture is
parametrised and most tests are medium-blind. The ones that are not say what they are
about: reopening a file, and the cached projection the file store reads through, which
is the only place where a read that is cheap could also be wrong.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from atlas.model import Agent, Assertion, Link, Node, Run, Schema, Segment, Source, Span, TypeDef
from atlas.store import Store, jsonl, open_store
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


def test_a_store_lists_the_sources_it_holds(store: Store) -> None:
    other = SOURCE.model_copy(update={"id": "src-000000002"})
    store.add_source(other)
    store.add_source(SOURCE)

    assert [s.id for s in store.sources()] == [SOURCE.id, other.id]


def test_a_node_is_fetched_by_id_without_projecting_the_whole_graph(store: Store) -> None:
    store.assert_(asserted("a-1", node("node-1", name="first"), at="2026-01-01T00:00:00Z"))
    store.assert_(asserted("a-2", node("node-2", name="second"), at="2026-01-01T00:00:01Z"))

    assert store.get_node("node-2").fields["name"] == "second"
    assert store.get_node("node-9") is None
    assert [n.id for n in store.get_nodes(["node-2", "node-9", "node-1"])] == ["node-2", "node-1"]
    assert store.get_nodes(()) == ()


def test_a_superseded_node_is_not_fetched_by_id(store: Store) -> None:
    store.assert_(asserted("a-1", node(name="first"), at="2026-01-01T00:00:00Z"))
    store.assert_(
        asserted("a-2", node(name="second"), at="2026-01-02T00:00:00Z", supersedes="a-1")
    )

    assert store.get_node("node-1").fields["name"] == "second"


def test_a_store_says_where_it_lives_and_where_an_artifact_may_go(store: Store) -> None:
    if isinstance(store, MemoryStore):
        assert store.location is None
        assert store.artifact("index.json") is None
    else:
        assert store.location is not None
        assert store.artifact("index.json") == store.location / "index.json"


def test_runs_are_recorded_and_come_back_in_order(store: Store) -> None:
    first = Run(id="run-1", at="2026-01-01T00:00:00Z", counts={"claimed": 9, "kept": 7})
    second = Run(id="run-2", at="2026-01-02T00:00:00Z", pipeline="build.yaml", seconds=1.5)
    store.add_run(first)
    store.add_run(second)

    assert store.runs() == (first, second)
    assert store.runs()[0].counts["kept"] == 7


def test_a_schema_version_resolves_back_to_the_schema_it_names(store: Store) -> None:
    schema = Schema(version=VERSION, types=(TypeDef(name="Method"),))
    store.add_schema(schema)
    store.add_schema(schema)

    assert store.get_schema(VERSION) == schema
    assert store.get_schema("unwritten") is None


def test_the_jsonl_log_is_parsed_once_until_it_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JsonlStore(tmp_path / "atlas")
    store.add_source(SOURCE)
    store.assert_(asserted("a-1", node(), at="2026-01-01T00:00:00Z"))
    parses = 0
    original = jsonl._read

    def counted(*arguments: object, **options: object) -> tuple:
        nonlocal parses
        parses += 1
        return original(*arguments, **options)

    monkeypatch.setattr(jsonl, "_read", counted)

    assert store.nodes() and store.get_node("node-1") and store.assertions()
    assert store.links() == ()
    assert parses == 1

    store.assert_(asserted("a-2", node("node-2"), at="2026-01-01T00:00:01Z"))

    assert len(store.nodes()) == 2
    assert parses == 2


def test_a_write_by_another_process_invalidates_the_cached_projection(tmp_path: Path) -> None:
    reader = JsonlStore(tmp_path / "atlas")
    reader.add_source(SOURCE)
    reader.assert_(asserted("a-1", node(), at="2026-01-01T00:00:00Z"))
    assert [n.id for n in reader.nodes()] == ["node-1"]

    writer = JsonlStore(tmp_path / "atlas")
    writer.add_source(SOURCE.model_copy(update={"id": "src-000000002"}))
    writer.assert_(asserted("a-2", node("node-2"), at="2026-01-01T00:00:01Z"))

    assert [n.id for n in reader.nodes()] == ["node-1", "node-2"]
    assert len(reader.sources()) == 2


def test_a_named_store_is_opened_from_a_specification(tmp_path: Path) -> None:
    assert isinstance(open_store("memory"), MemoryStore)

    opened = open_store({"jsonl": {"dir": "store"}}, base=tmp_path)

    assert opened.location == tmp_path / "store"
    assert open_store("jsonl", base=tmp_path).location == tmp_path / "store"


def test_an_unknown_or_malformed_store_specification_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown store 'postgres'"):
        open_store({"postgres": {"dsn": "..."}}, base=tmp_path)
    with pytest.raises(ValueError, match="one name with its options"):
        open_store({"jsonl": {}, "memory": {}})
