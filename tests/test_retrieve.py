"""Tests for the ranking: the obviously relevant node first, in either language.

The default scoring has one job and one documented limit, and both are asserted here:
a node sharing terms with the question ranks above one that does not, a shorter node
wins a tie on breadth, and a question phrased in words the corpus does not use finds
nothing at all. The rest is the seam -- a consumer wanting another ranking writes a
step and names it, and the store, not the index, decides which nodes still exist.
"""

from __future__ import annotations

import pytest

from atlas.model import Agent, Assertion, Node, Segment, Source, Span
from atlas.steps import get, register
from atlas.steps.index_nodes import Index
from atlas.steps.retrieve import LIMIT, Hit, RetrieveOptions, overlap, retrieve
from atlas.store.memory import MemoryStore

SEGMENTS = (
    "Разработана модель прогнозирования отказов оборудования.\n",
    "Точность распознавания на тестовой выборке составила 0,94.\n",
    "The pipeline reached an F-score of 0.91 on held-out data.\n",
)
VERSION = "0" * 12
SOURCE = Source(
    id="doc-1",
    origin="corpus/doc-1.txt",
    segments=tuple(Segment(number=n, text=t) for n, t in enumerate(SEGMENTS, start=1)),
)
AGENT = Agent(id="agent-m", kind="model", label="extractor")


def node(node_id: str, segment: int, quote: str, **fields: str) -> Node:
    text = SOURCE.segment_text(segment)
    start = text.index(quote)
    return Node(
        id=node_id,
        type="Thing",
        spans=(Span.of(SOURCE, segment, start, start + len(quote)),),
        schema_version=VERSION,
        fields=fields,
    )


METHOD = node("n-1", 1, "модель прогнозирования отказов оборудования", name="модель")
RESULT = node("n-2", 2, "Точность распознавания на тестовой выборке составила 0,94", value="0,94")
ENGLISH = node("n-3", 3, "F-score of 0.91 on held-out data", name="F-score")


@pytest.fixture
def store() -> MemoryStore:
    made = MemoryStore()
    made.add_source(SOURCE)
    for number, target in enumerate((METHOD, RESULT, ENGLISH), start=1):
        made.assert_(Assertion(id=f"a-{number}", agent=AGENT, at="2025-01-01T00:00:00+00:00",
                               target=target))
    return made


def state_for(store: MemoryStore, question: str) -> dict:
    return {"store": store, "index": Index.of(store.nodes()), "question": question}


def test_the_relevant_node_ranks_first(store: MemoryStore) -> None:
    state = state_for(store, "Какая точность на тестовой выборке?")

    hits = retrieve(state, RetrieveOptions())["hits"]

    assert isinstance(hits[0], Hit)
    assert hits[0].node.id == RESULT.id
    assert hits[0].score > 0


def test_the_same_ranking_works_in_the_other_language(store: MemoryStore) -> None:
    """Nothing in the scoring is written per language: the terms come from the folding."""
    state = state_for(store, "What F‑score did the pipeline reach?")

    hits = retrieve(state, RetrieveOptions())["hits"]

    assert hits[0].node.id == ENGLISH.id


def test_a_question_sharing_no_term_retrieves_nothing(store: MemoryStore) -> None:
    assert retrieve(state_for(store, "квантовая запутанность"), RetrieveOptions())["hits"] == ()


def test_the_limit_is_the_number_of_hits(store: MemoryStore) -> None:
    every = "модель точность f-score"

    assert len(retrieve(state_for(store, every), RetrieveOptions())["hits"]) == 3
    assert len(retrieve(state_for(store, every), RetrieveOptions(limit=1))["hits"]) == 1


def test_the_shorter_of_two_matching_nodes_wins() -> None:
    """The length normalisation is the whole of the ranking beyond the overlap."""
    short = node("n-4", 1, "модель", name="модель")

    scores = overlap(Index.of((METHOD, short)), "модель")

    assert scores[short.id] > scores[METHOD.id]


def test_a_node_the_store_no_longer_projects_is_not_returned(store: MemoryStore) -> None:
    state = state_for(store, "Какая точность на тестовой выборке?")
    corrected = node("n-5", 2, "Точность распознавания", value="0,94")
    store.assert_(Assertion(id="a-9", agent=AGENT, at="2025-02-01T00:00:00+00:00",
                            target=corrected, supersedes="a-2"))

    hits = retrieve(state, RetrieveOptions())["hits"]

    assert RESULT.id not in {hit.node.id for hit in hits}


def test_a_consumer_ranks_differently_by_naming_its_own_step(store: MemoryStore) -> None:
    """The seam for another ranking is the one the library already has: another step.

    Nothing inside `retrieve` has to be configurable for this to work -- the consumer
    keeps `Index`, `Hit` and the store lookup, and replaces only the order.
    """

    @register("retrieve_reversed", requires=("store", "index"), produces=("hits",))
    def retrieve_reversed(state: dict) -> dict:
        ids = sorted(state["index"].lengths, reverse=True)
        return {"hits": tuple(Hit(node=node, score=1.0)
                              for node in state["store"].get_nodes(ids))}

    hits = get("retrieve_reversed")(state_for(store, "точность"))["hits"]

    assert [hit.node.id for hit in hits] == sorted(
        [METHOD.id, RESULT.id, ENGLISH.id], reverse=True)


def test_the_step_declares_what_it_reads_what_it_adds_and_what_it_takes() -> None:
    step = get("retrieve")

    assert step.requires == ("store", "index", "question")
    assert step.produces == ("hits",)
    assert step.options is RetrieveOptions
    assert RetrieveOptions().limit == LIMIT


def test_a_step_called_through_the_registry_gets_the_defaults_its_model_carries(
    store: MemoryStore
) -> None:
    """Nothing configured is not nothing given: the model is where the default lives."""
    hits = get("retrieve")(state_for(store, "модель точность f-score"))["hits"]

    assert len(hits) == 3
