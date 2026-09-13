"""Tests for the metamodel: what a source fixes, and what evidence a graph object owes.

The properties under test are the ones the rest of the library is allowed to assume:
a span cuts its own text out of its source, nothing typed exists without such a span,
a link's id follows from what it relates, and the graph is a projection of a log.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas.model import Agent, Assertion, Link, Node, Segment, Source, Span, current

FIRST = "The task is to segment cells.\nWe introduce a model.\n"
SECOND = "The model reached 0.912 on the held-out set.\n"

SOURCE = Source(
    id="src-000000001",
    origin="corpus/paper.pdf",
    segments=(Segment(number=1, text=FIRST), Segment(number=2, text=SECOND)),
)
OTHER = Source(
    id="src-000000002", origin="corpus/other.pdf", segments=(Segment(number=1, text=FIRST),)
)


def span(source: Source = SOURCE, segment: int = 1, quote: str = "segment cells") -> Span:
    start = source.segment_text(segment).index(quote)
    return Span.of(source, segment, start, start + len(quote))


def node(**overrides: object) -> Node:
    fields: dict = {
        "id": "node-1",
        "type": "Method",
        "spans": (span(),),
        "schema_version": "0" * 12,
    }
    return Node(**(fields | overrides))


def test_span_of_takes_its_text_from_the_source() -> None:
    cut = span(quote="a model")

    assert cut.text == "a model"
    assert cut.source_id == SOURCE.id
    assert cut.covers(SOURCE.segment_text(1))


def test_a_span_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="empty span"):
        Span.of(SOURCE, 1, 4, 4)


def test_offsets_and_text_cannot_disagree() -> None:
    with pytest.raises(ValidationError):
        Span(source_id=SOURCE.id, segment=1, start=0, end=4, text="a longer quote")


def test_a_span_stops_covering_text_that_drifted() -> None:
    cut = span()

    assert not cut.covers(FIRST.replace("segment", "segmen t"))


def test_the_text_hash_names_the_text_layer_and_not_the_source() -> None:
    reparsed = Source(
        id=SOURCE.id,
        origin=SOURCE.origin,
        segments=(Segment(number=1, text=FIRST.replace("cells", "cell s")), SOURCE.segments[1]),
    )

    assert reparsed.id == SOURCE.id
    assert reparsed.text_hash != SOURCE.text_hash
    assert SOURCE.text_hash == Source(**SOURCE.model_dump()).text_hash


def test_a_missing_segment_is_an_error_rather_than_an_empty_string() -> None:
    with pytest.raises(KeyError, match="segment 9"):
        SOURCE.segment_text(9)


def test_a_source_without_segments_is_refused() -> None:
    with pytest.raises(ValidationError):
        Source(id="src-000000003", origin="nothing.pdf", segments=())


def test_no_node_without_provenance() -> None:
    with pytest.raises(ValidationError):
        node(spans=())


def test_evidence_may_not_straddle_two_sources() -> None:
    with pytest.raises(ValidationError, match="more than one source"):
        node(spans=(span(), span(OTHER)))
    with pytest.raises(ValidationError, match="more than one source"):
        Link.of("addresses", "node-1", "node-2", (span(), span(OTHER)), "0" * 12)


def test_a_node_is_a_frozen_value() -> None:
    with pytest.raises(ValidationError):
        node().type = "Task"
    with pytest.raises(ValidationError):
        node(run_id="run-1")


def test_a_link_id_follows_from_what_it_relates_and_stands_on() -> None:
    spans = (span(), span(segment=2, quote="0.912"))
    link = Link.of("evaluated_on", "node-1", "node-2", spans, "0" * 12)

    assert link.id == Link.of("evaluated_on", "node-1", "node-2", spans[::-1], "0" * 12).id
    assert link.id == Link.of("evaluated_on", "node-1", "node-2", spans, "0" * 12, {"n": "1"}).id
    assert link.id != Link.of("evaluated_on", "node-1", "node-3", spans, "0" * 12).id
    assert link.id != Link.of("addresses", "node-1", "node-2", spans, "0" * 12).id
    assert link.id != Link.of("evaluated_on", "node-1", "node-2", spans[:1], "0" * 12).id


def assertion(ident: str, at: str, target: Node | Link, supersedes: str | None = None) -> Assertion:
    agent = Agent(id="agent-1", kind="model", label="a run")
    return Assertion(id=ident, agent=agent, at=at, target=target, supersedes=supersedes)


def test_current_keeps_the_latest_assertion_per_target() -> None:
    first = assertion("a1", "2024-01-01T00:00:00Z", node(fields={"name": "early"}))
    second = assertion("a2", "2024-02-01T00:00:00Z", node(fields={"name": "late"}))

    assert current([first, second]) == (second.target,)
    assert current([second, first]) == (second.target,)


def test_a_superseded_assertion_never_resurfaces() -> None:
    old = assertion("a1", "2024-03-01T00:00:00Z", node(fields={"name": "machine"}))
    correction = assertion("a2", "2024-01-01T00:00:00Z", node(fields={"name": "human"}), "a1")

    assert current([old, correction]) == (correction.target,)


def test_current_projects_nodes_and_links_side_by_side() -> None:
    link = Link.of("addresses", "node-1", "node-2", (span(),), "0" * 12)
    log = [
        assertion("a1", "2024-01-01T00:00:00Z", node()),
        assertion("a2", "2024-01-02T00:00:00Z", link),
    ]

    assert current(log) == (log[0].target, link)


def test_an_empty_log_projects_to_nothing() -> None:
    assert current([]) == ()


def test_an_assertion_survives_the_form_it_is_stored_in() -> None:
    """The log is written as JSON, so a target must come back as the class it went in as."""
    link = Link.of("addresses", "node-1", "node-2", (span(),), "0" * 12)

    for target in (node(), link):
        written = assertion("a1", "2024-01-01T00:00:00Z", target)
        restored = Assertion.model_validate_json(written.model_dump_json())

        assert restored == written
        assert type(restored.target) is type(target)
