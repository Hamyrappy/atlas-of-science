"""Tests for quote relocation.

Every successful case re-slices the returned offsets out of the page text and
compares them with the span's own text, because that round trip is the only
property the rest of the pipeline is allowed to rely on.
"""

from __future__ import annotations

import pytest

from atlas.contracts import Document, Page, Span
from atlas.extract.relocate import THRESHOLD, Match, locate

PAGE_ONE = (
    "The task is to segment cells in microscopy images.\n"
    "We introduce a convolutional model trained on\nthe public benchmark.\n"
    "Scores were recorded over 2019–2021 on the “gold” subset.\n"
    "Results are reported below.\n"
)

PAGE_TWO = (
    "The model reached an F1 score of 0.912 on the validation split.\n"
    "Ablating the attention block costs 3.4 points of F1.\n"
    "Results are reported below.\n"
)


@pytest.fixture
def document() -> Document:
    return Document(
        id="doc-1",
        source="corpus/doc-1.pdf",
        pages=(Page(number=1, text=PAGE_ONE), Page(number=2, text=PAGE_TWO)),
    )


def round_trip(document: Document, match: Match) -> str:
    span = match.span
    sliced = document.page_text(span.page)[span.start : span.end]
    assert sliced == span.text
    assert span.doc_id == document.id
    return sliced


def test_exact_quote_is_located_verbatim(document: Document) -> None:
    match = locate(document, "segment cells in microscopy images")

    assert match is not None
    assert match.method == "exact"
    assert match.confidence == 1.0
    assert match.needs_review is False
    assert match.span.page == 1
    assert round_trip(document, match) == "segment cells in microscopy images"


def test_extra_internal_whitespace_is_collapsed(document: Document) -> None:
    match = locate(document, "trained on   the public\tbenchmark")

    assert match is not None
    assert match.method == "normalised"
    assert match.confidence == 0.9
    assert match.needs_review is False
    assert round_trip(document, match) == "trained on\nthe public benchmark"

    padded = locate(document, "  trained on the public benchmark\n")
    assert padded is not None and padded.span == match.span


def test_straight_quotes_and_hyphen_match_curly_quotes_and_en_dash(document: Document) -> None:
    match = locate(document, 'recorded over 2019-2021 on the "gold" subset')

    assert match is not None
    assert match.method == "normalised"
    assert round_trip(document, match) == "recorded over 2019–2021 on the “gold” subset"


def test_quote_from_second_page_is_found_without_a_hint(document: Document) -> None:
    match = locate(document, "Ablating the attention block")

    assert match is not None
    assert match.span.page == 2
    assert match.method == "exact"
    assert round_trip(document, match) == "Ablating the attention block"


def test_quote_from_second_page_is_found_with_a_hint(document: Document) -> None:
    match = locate(document, "Ablating the attention block", page_hint=2)

    assert match is not None
    assert match.span.page == 2
    assert round_trip(document, match) == "Ablating the attention block"


def test_hint_decides_which_page_an_ambiguous_quote_comes_from(document: Document) -> None:
    quote = "Results are reported below."
    without_hint = locate(document, quote)
    with_hint = locate(document, quote, page_hint=2)

    assert without_hint is not None and without_hint.span.page == 1
    assert with_hint is not None and with_hint.span.page == 2
    assert round_trip(document, with_hint) == quote


def test_typo_in_the_quote_falls_through_to_fuzzy(document: Document) -> None:
    match = locate(document, "the modle reached an F1 score of 0.912 on the validaton split")

    assert match is not None
    assert match.method == "fuzzy"
    assert match.needs_review is True
    assert THRESHOLD / 100 <= match.confidence < 1.0
    assert match.span.page == 2
    assert "F1 score of 0.912" in round_trip(document, match)


def test_fuzzy_span_covers_whole_words(document: Document) -> None:
    left = locate(document, "blating the attention block costs 3.4 ponts")
    right = locate(document, "segment cells in microscopy images.\nWe introdue")

    assert left is not None and right is not None
    assert left.method == "fuzzy" and right.method == "fuzzy"
    assert round_trip(document, left) == "Ablating the attention block costs 3.4 points"
    assert round_trip(document, right) == "segment cells in microscopy images.\nWe introduce"


def test_hint_decides_which_page_a_fuzzy_quote_comes_from(document: Document) -> None:
    quote = "Results are reportd below."
    without_hint = locate(document, quote)
    with_hint = locate(document, quote, page_hint=2)

    assert without_hint is not None and without_hint.method == "fuzzy"
    assert without_hint.span.page == 1
    assert with_hint is not None and with_hint.span.page == 2
    assert round_trip(document, with_hint) == "Results are reported below."


def test_absent_quote_is_not_located(document: Document) -> None:
    assert locate(document, "trapped ions in a quantum register") is None


@pytest.mark.parametrize("quote", ["", "   ", "\n\t "])
def test_empty_quote_is_not_located(document: Document, quote: str) -> None:
    assert locate(document, quote) is None


def test_quote_longer_than_the_page_is_not_located(document: Document) -> None:
    assert locate(document, PAGE_ONE + PAGE_TWO, page_hint=1) is None


def test_span_of_cannot_disagree_with_its_document(document: Document) -> None:
    """The classmethod takes the text from the page, so offsets and quote cannot drift."""
    page_text = document.page_text(1)
    start = page_text.index("Results")

    span = Span.of(document, 1, start, start + 7)

    assert span.text == "Results"
    assert span.covers(page_text)
    with pytest.raises(ValueError, match="empty span"):
        Span.of(document, 1, start, start)
