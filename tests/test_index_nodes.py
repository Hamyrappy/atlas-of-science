"""Tests for the node index: the terms it stores, and the file it reuses.

Two claims are under test. The terms are the library's -- whatever `atlas.text` folds
together is one term here too, or a quote placed through relocation would be indexed
under a spelling no question produces. And the artifact is a cache and behaves like one:
written where the store says, reused while it describes the same nodes, rebuilt when it
does not, and simply absent for a store that lives nowhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.model import Agent, Assertion, Node, Segment, Source, Span
from atlas.steps import get
from atlas.steps.index_nodes import Index, index_nodes, signature
from atlas.store.jsonl import JsonlStore
from atlas.store.memory import MemoryStore

TEXT = (
    "The F‑score reached 0.91 on held-out data.\n"
    "Точность на тестовой выборке составила 0,94.\n"
)
VERSION = "0" * 12
SOURCE = Source(id="doc-1", origin="corpus/doc-1.txt", segments=(Segment(number=1, text=TEXT),))
AGENT = Agent(id="agent-m", kind="model", label="extractor")


def node(node_id: str, quote: str, **fields: str) -> Node:
    start = TEXT.index(quote)
    return Node(
        id=node_id,
        type="Thing",
        spans=(Span.of(SOURCE, 1, start, start + len(quote)),),
        schema_version=VERSION,
        fields=fields,
    )


FIRST = node("n-1", "The F‑score reached 0.91", name="F‑score")
SECOND = node("n-2", "Точность на тестовой выборке составила 0,94", name="точность")


@pytest.fixture
def store(tmp_path: Path) -> JsonlStore:
    made = JsonlStore(tmp_path / "store")
    made.add_source(SOURCE)
    for number, target in enumerate((FIRST, SECOND), start=1):
        made.assert_(Assertion(id=f"a-{number}", agent=AGENT, at="2025-01-01T00:00:00+00:00",
                               target=target))
    return made


def test_the_index_folds_a_term_the_way_the_rest_of_the_library_does() -> None:
    index = Index.of((FIRST,))

    assert index.postings["f-score"] == {FIRST.id: 2}
    assert "f‑score" not in index.postings


def test_a_node_is_indexed_under_its_fields_and_its_quotes() -> None:
    index = Index.of((node("n-3", "held-out data", label="unquoted"),))

    assert set(index.postings) >= {"unquoted", "held-out", "data"}
    assert index.lengths["n-3"] == 3


def test_the_index_is_written_where_the_store_says_and_reads_back_the_same(store) -> None:
    built = index_nodes({"store": store})["index"]

    path = store.artifact("index.json")
    assert path.exists()
    assert Index.load(path) == built
    assert built.signature == signature(store.nodes())


def test_the_file_is_reused_while_it_describes_the_same_nodes(store, monkeypatch) -> None:
    index_nodes({"store": store})
    monkeypatch.setattr(Index, "of", classmethod(lambda cls, nodes: pytest.fail("rebuilt")))

    assert len(index_nodes({"store": store})["index"]) == 2


def test_rebuild_ignores_a_file_that_would_have_fitted(store, monkeypatch) -> None:
    index_nodes({"store": store})
    monkeypatch.setattr(Index, "load", classmethod(lambda cls, path: pytest.fail("reused")))

    assert len(index_nodes({"store": store}, rebuild=True)["index"]) == 2


def test_another_node_in_the_store_invalidates_the_file(store) -> None:
    index_nodes({"store": store})
    third = node("n-3", "held-out data", name="data")
    store.assert_(Assertion(id="a-3", agent=AGENT, at="2025-01-02T00:00:00+00:00", target=third))

    state = index_nodes({"store": store})

    assert len(state["index"]) == 3
    assert Index.load(store.artifact("index.json")).signature == signature(store.nodes())


def test_a_truncated_file_is_a_cache_miss(store) -> None:
    index_nodes({"store": store})
    store.artifact("index.json").write_text("{\"signa", encoding="utf-8")

    assert len(index_nodes({"store": store})["index"]) == 2


def test_a_store_that_lives_nowhere_indexes_without_persisting() -> None:
    memory = MemoryStore()
    memory.add_source(SOURCE)
    memory.assert_(Assertion(id="a-1", agent=AGENT, at="2025-01-01T00:00:00+00:00", target=FIRST))

    state = index_nodes({"store": memory})

    assert memory.artifact("index.json") is None
    assert len(state["index"]) == 1


def test_the_step_declares_what_it_reads_and_adds() -> None:
    step = get("index_nodes")

    assert (step.requires, step.produces) == (("store",), ("index",))
