"""Tests for quote relocation and for the nodes it mints.

Every successful case re-slices the returned offsets out of the segment text and
compares them with the span's own text, because that round trip is the only property
the rest of the pipeline is allowed to rely on. The schema here is a stub: the step
stamps its version onto the nodes and asks it nothing else.
"""

from __future__ import annotations

import re

import pytest

from atlas.model import Schema, Segment, Source, Span
from atlas.steps import get
from atlas.steps.relocate import THRESHOLD, Match, Statement, locate

FIRST = (
    "The task is to segment cells in microscopy images.\n"
    "We introduce a convolutional model trained on\nthe public benchmark.\n"
    "Scores were recorded over 2019–2021 on the “gold” subset.\n"
    "Results are reported below.\n"
)

SECOND = (
    "The model reached an F1 score of 0.912 on the validation split.\n"
    "Ablating the attention block costs 3.4 points of F1.\n"
    "Results are reported below.\n"
)

SCHEMA = Schema(version="0" * 12)


@pytest.fixture
def source() -> Source:
    return Source(
        id="src-1",
        origin="corpus/src-1.pdf",
        segments=(Segment(number=1, text=FIRST), Segment(number=2, text=SECOND)),
    )


def round_trip(source: Source, match: Match) -> str:
    span = match.span
    sliced = source.segment_text(span.segment)[span.start : span.end]
    assert sliced == span.text
    assert span.source_id == source.id
    return sliced


def statement(quote: str, segment: int = 1, **fields: str) -> Statement:
    return Statement(source_id="src-1", segment=segment, type="Thing", fields=fields, quote=quote)


def relocate(source: Source, *statements: Statement) -> dict:
    return get("relocate")({"sources": (source,), "schema": SCHEMA, "statements": statements})


def test_exact_quote_is_located_verbatim(source: Source) -> None:
    match = locate(source, "segment cells in microscopy images")

    assert match is not None
    assert match.method == "exact"
    assert match.confidence == 1.0
    assert match.needs_review is False
    assert match.span.segment == 1
    assert round_trip(source, match) == "segment cells in microscopy images"


def test_extra_internal_whitespace_is_collapsed(source: Source) -> None:
    match = locate(source, "trained on   the public\tbenchmark")

    assert match is not None
    assert match.method == "normalised"
    assert match.confidence == 0.9
    assert match.needs_review is False
    assert round_trip(source, match) == "trained on\nthe public benchmark"

    padded = locate(source, "  trained on the public benchmark\n")
    assert padded is not None and padded.span == match.span


def test_straight_quotes_and_hyphen_match_curly_quotes_and_en_dash(source: Source) -> None:
    match = locate(source, 'recorded over 2019-2021 on the "gold" subset')

    assert match is not None
    assert match.method == "normalised"
    assert round_trip(source, match) == "recorded over 2019–2021 on the “gold” subset"


def test_quote_from_the_second_segment_is_found_without_a_hint(source: Source) -> None:
    match = locate(source, "Ablating the attention block")

    assert match is not None
    assert match.span.segment == 2
    assert match.method == "exact"
    assert round_trip(source, match) == "Ablating the attention block"


def test_hint_decides_which_segment_an_ambiguous_quote_comes_from(source: Source) -> None:
    quote = "Results are reported below."
    without_hint = locate(source, quote)
    with_hint = locate(source, quote, segment_hint=2)

    assert without_hint is not None and without_hint.span.segment == 1
    assert with_hint is not None and with_hint.span.segment == 2
    assert round_trip(source, with_hint) == quote


def test_typo_in_the_quote_falls_through_to_fuzzy(source: Source) -> None:
    match = locate(source, "the modle reached an F1 score of 0.912 on the validaton split")

    assert match is not None
    assert match.method == "fuzzy"
    assert match.needs_review is True
    assert THRESHOLD / 100 <= match.confidence < 1.0
    assert match.span.segment == 2
    assert "F1 score of 0.912" in round_trip(source, match)


def test_fuzzy_span_covers_whole_words(source: Source) -> None:
    left = locate(source, "blating the attention block costs 3.4 ponts")
    right = locate(source, "segment cells in microscopy images.\nWe introdue")

    assert left is not None and right is not None
    assert left.method == "fuzzy" and right.method == "fuzzy"
    assert round_trip(source, left) == "Ablating the attention block costs 3.4 points"
    assert round_trip(source, right) == "segment cells in microscopy images.\nWe introduce"


def test_hint_decides_which_segment_a_fuzzy_quote_comes_from(source: Source) -> None:
    quote = "Results are reportd below."
    without_hint = locate(source, quote)
    with_hint = locate(source, quote, segment_hint=2)

    assert without_hint is not None and without_hint.method == "fuzzy"
    assert without_hint.span.segment == 1
    assert with_hint is not None and with_hint.span.segment == 2
    assert round_trip(source, with_hint) == "Results are reported below."


def test_absent_quote_is_not_located(source: Source) -> None:
    assert locate(source, "trapped ions in a quantum register") is None


@pytest.mark.parametrize("quote", ["", "   ", "\n\t "])
def test_empty_quote_is_not_located(source: Source, quote: str) -> None:
    assert locate(source, quote) is None


def test_quote_longer_than_the_segment_is_not_located(source: Source) -> None:
    assert locate(source, FIRST + SECOND, segment_hint=1) is None


def test_span_of_cannot_disagree_with_its_source(source: Source) -> None:
    """The classmethod takes the text from the segment, so offsets and quote cannot drift."""
    text = source.segment_text(1)
    start = text.index("Results")

    span = Span.of(source, 1, start, start + 7)

    assert span.text == "Results"
    assert span.covers(text)
    with pytest.raises(ValueError, match="empty span"):
        Span.of(source, 1, start, start)


def test_the_step_mints_one_located_node_per_statement(source: Source) -> None:
    state = relocate(source, statement("segment cells"), statement("Ablating", segment=2))

    assert (state["unplaced"], state["needs_review"]) == (0, 0)
    assert [node.spans[0].segment for node in state["nodes"]] == [1, 2]
    for node in state["nodes"]:
        span = node.spans[0]
        assert source.segment_text(span.segment)[span.start : span.end] == span.text
        assert node.schema_version == SCHEMA.version


def test_an_invented_quote_is_dropped_and_counted(source: Source) -> None:
    state = relocate(source, statement("Our transformer read eight million documents."))

    assert state["nodes"] == ()
    assert state["unplaced"] == 1


def test_an_inexact_quote_is_placed_but_flagged_for_review(source: Source) -> None:
    state = relocate(source, statement("the modle reached an F1 score of 0.912", segment=2))

    assert state["needs_review"] == 1
    assert "F1 score of 0.912" in state["nodes"][0].spans[0].text


def test_ids_are_stable_across_runs_and_identify_one_node(source: Source) -> None:
    first = relocate(source, statement("segment cells"), statement("Ablating", segment=2))
    again = relocate(source, statement("segment cells"), statement("Ablating", segment=2))
    twice = relocate(source, statement("segment cells"), statement("segment cells"))

    assert [n.id for n in first["nodes"]] == [n.id for n in again["nodes"]]
    assert len({n.id for n in first["nodes"]}) == 2
    assert len(twice["nodes"]) == 1


def test_two_statements_sharing_a_quote_both_survive(source: Source) -> None:
    """One sentence can carry two statements; hashing the quote alone lost the second."""
    state = relocate(
        source,
        statement("Results are reported below.", value="0.12"),
        statement("Results are reported below.", value="0.19"),
    )

    assert len(state["nodes"]) == 2
    assert len({node.id for node in state["nodes"]}) == 2


def test_the_threshold_is_a_constant_and_a_file_calling_it_an_option_is_refused() -> None:
    """THRESHOLD is not configurable, so a configuration setting it is told, not ignored."""
    with pytest.raises(ValueError, match=re.escape(
        "step 'relocate': unknown option 'threshold'. It takes no options"
    )):
        get("relocate").configure({"threshold": THRESHOLD - 10})
