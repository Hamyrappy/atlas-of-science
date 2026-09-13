"""Turning a quoted fragment back into a Span.

A model is asked for a verbatim quote and never for character offsets, which it
would invent; the offsets are recovered here by searching the source text. Every
relaxation of the search runs on a folded copy of the page that keeps a map back
to the original, so the span that comes out re-slices to exactly its own text.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from rapidfuzz import fuzz

from atlas.contracts import Document, Frozen, Page, Span

THRESHOLD = 85.0
"""Lowest rapidfuzz partial ratio (0-100) that still counts as a location. Below
it a quote is reported as absent rather than placed somewhere plausible."""

_FOLD = {
    **{ord(c): "-" for c in "‐‑‒–—―−"},
    **{ord(c): "'" for c in "‘’‚‛′´"},
    **{ord(c): '"' for c in "“”„‟″«»"},
}


class Match(Frozen):
    """Where a quote was found, and how much the search had to be relaxed to find it."""

    span: Span
    confidence: float
    method: Literal["exact", "normalised", "fuzzy"]
    needs_review: bool = False


class _Searchable(NamedTuple):
    """A page with its normalised text and the source offset of each normalised character."""

    page: Page
    normalised: str
    offsets: tuple[int, ...]


def locate(document: Document, quote: str, page_hint: int | None = None) -> Match | None:
    """Locate `quote` in `document`, or return None if it cannot be placed."""
    if not quote.strip():
        return None
    pages = sorted(document.pages, key=lambda page: page.number != page_hint)

    for page in pages:
        start = page.text.find(quote)
        if start >= 0:
            span = _span_at(document, page.number, start, start + len(quote))
            return Match(span=span, confidence=1.0, method="exact")

    normalised_quote, _ = _normalise(quote)
    folded = (_Searchable(page, *_normalise(page.text)) for page in pages)
    # A quote longer than a page cannot have come from it, however well it aligns.
    candidates = [item for item in folded if len(item.normalised) >= len(normalised_quote)]

    for candidate in candidates:
        hit = candidate.normalised.find(normalised_quote)
        if hit >= 0:
            start, end = _to_original(candidate.offsets, hit, hit + len(normalised_quote))
            span = _span_at(document, candidate.page.number, start, end)
            return Match(span=span, confidence=0.9, method="normalised")

    return _fuzzy(document, normalised_quote, candidates)


def _fuzzy(document: Document, normalised: str, candidates: list[_Searchable]) -> Match | None:
    """The best-scoring alignment over the candidate pages, or None below THRESHOLD."""
    aligned: list[tuple[float, _Searchable, int, int]] = []
    for candidate in candidates:
        alignment = fuzz.partial_ratio_alignment(
            normalised, candidate.normalised, score_cutoff=THRESHOLD
        )
        if alignment is not None:
            aligned.append((alignment.score, candidate, alignment.dest_start, alignment.dest_end))
    if not aligned:
        return None

    # `max` keeps the first of equal scores, and the candidates lead with the hint.
    score, candidate, dest_start, dest_end = max(aligned, key=lambda hit: hit[0])
    start, end = _to_original(candidate.offsets, dest_start, dest_end)
    start, end = _whole_words(candidate.page.text, start, end)
    span = _span_at(document, candidate.page.number, start, end)
    return Match(span=span, confidence=score / 100, method="fuzzy", needs_review=True)


def _normalise(text: str) -> tuple[str, tuple[int, ...]]:
    """Fold dashes and quotes, collapse whitespace runs, record each character's source offset.

    A collapsed run maps to its first character, so an edge landing on the run
    trims back to the end of the preceding word rather than into it.
    """
    characters: list[str] = []
    offsets: list[int] = []
    space_at: int | None = None
    for index, character in enumerate(text):
        if character.isspace():
            if space_at is None:
                space_at = index
            continue
        if space_at is not None:
            if characters:
                characters.append(" ")
                offsets.append(space_at)
            space_at = None
        characters.append(_FOLD.get(ord(character), character))
        offsets.append(index)
    return "".join(characters), tuple(offsets)


def _to_original(offsets: tuple[int, ...], start: int, end: int) -> tuple[int, int]:
    """Map a half-open range of normalised offsets onto the original text."""
    return offsets[start], offsets[end - 1] + 1


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _whole_words(text: str, start: int, end: int) -> tuple[int, int]:
    """Complete the words a range cuts through.

    Alignment stops wherever the cheapest path does, routinely mid word, and half
    a word is worthless as provenance. An edge already on whitespace cuts no word.
    """
    start, end = _trim(text, start, end)
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return start, end


def _span_at(document: Document, page: int, start: int, end: int) -> Span:
    """Build a span from offsets on the page text, after completing any cut word."""
    start, end = _trim(document.page_text(page), start, end)
    return Span.of(document, page, start, end)
