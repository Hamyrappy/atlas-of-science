"""Turning a quoted fragment back into a span, and a placed statement into a node.

An extractor is asked for a verbatim quote and never for character offsets, which a
model would invent; the offsets are recovered here by searching the text of the source,
on a folded copy that maps back onto it, so the span that comes out re-slices to exactly
its own text. This is where nodes are minted, because a node may not exist without a
located span: a quote that cannot be placed is dropped and counted rather than guessed
at, and that is the whole reason the step is separate from whatever produced it.
"""

from __future__ import annotations

import hashlib
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

from atlas.model import Frozen, Node, Segment, Source, Span
from atlas.steps import Nothing, State, register
from atlas.text import fold, to_original, trim, whole_words

THRESHOLD = 85.0
"""Lowest rapidfuzz partial ratio (0-100) that still counts as a location. Below
it a quote is reported as absent rather than placed somewhere plausible."""


class Statement(BaseModel):
    """What an extractor claims about one segment, before it has been placed in the text.

    This is the contract between any extractor and this step, which is why it is
    declared here and not next to the one extractor the library ships. Keys nobody
    declared are ignored rather than fatal: a model volunteers them.
    """

    model_config = ConfigDict(frozen=True)

    source_id: str
    segment: int
    type: str
    fields: dict[str, str] = Field(default_factory=dict)
    quote: str


class Match(Frozen):
    """Where a quote was found, and how much the search had to be relaxed to find it."""

    span: Span
    confidence: float
    method: Literal["exact", "normalised", "fuzzy"]
    needs_review: bool = False


class _Searchable(NamedTuple):
    """A segment with its folded text and the source offset of each folded character."""

    segment: Segment
    folded: str
    offsets: tuple[int, ...]


@register("relocate", requires=("sources", "statements", "schema"),
          produces=("nodes", "unplaced", "needs_review"), options=Nothing)
def relocate(state: State) -> State:
    """Place every statement in its source and mint a node for each one that lands."""
    sources = {source.id: source for source in state["sources"]}
    version = state["schema"].version
    nodes: dict[str, Node] = {}
    unplaced = 0
    needs_review = 0
    for statement in state["statements"]:
        match = locate(sources[statement.source_id], statement.quote, statement.segment)
        if match is None:
            unplaced += 1
            continue
        node = Node(
            id=_node_id(statement, match.span),
            type=statement.type,
            fields=statement.fields,
            spans=(match.span,),
            schema_version=version,
        )
        # The same statement can come back while another segment is read: one node, and
        # a repeat is not a loss. Two statements sharing a quote differ in their fields.
        if node.id not in nodes:
            nodes[node.id] = node
            needs_review += match.needs_review
    return {"nodes": tuple(nodes.values()), "unplaced": unplaced, "needs_review": needs_review}


def _node_id(statement: Statement, span: Span) -> str:
    """A content hash of what is stored, so a rerun over unchanged input rewrites the id.

    The fields are part of the material: one sentence can carry two statements, and
    hashing the quote alone made the second a duplicate of the first and dropped it.
    """
    rendered = "\x1f".join(f"{key}={statement.fields[key]}" for key in sorted(statement.fields))
    place = f"{span.segment}:{span.start}:{span.end}"
    material = "\x00".join([span.source_id, place, statement.type, rendered])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def locate(source: Source, quote: str, segment_hint: int | None = None) -> Match | None:
    """Locate `quote` in `source`, or return None if it cannot be placed."""
    if not quote.strip():
        return None
    segments = sorted(source.segments, key=lambda segment: segment.number != segment_hint)

    for segment in segments:
        start = segment.text.find(quote)
        if start >= 0:
            span = _span_at(source, segment.number, start, start + len(quote))
            return Match(span=span, confidence=1.0, method="exact")

    folded_quote, _ = fold(quote)
    folded = (_Searchable(segment, *fold(segment.text)) for segment in segments)
    # A quote longer than a segment cannot have come from it, however well it aligns.
    candidates = [item for item in folded if len(item.folded) >= len(folded_quote)]

    for candidate in candidates:
        hit = candidate.folded.find(folded_quote)
        if hit >= 0:
            start, end = to_original(candidate.offsets, hit, hit + len(folded_quote))
            span = _span_at(source, candidate.segment.number, start, end)
            return Match(span=span, confidence=0.9, method="normalised")

    return _fuzzy(source, folded_quote, candidates)


def _fuzzy(source: Source, folded: str, candidates: list[_Searchable]) -> Match | None:
    """The best-scoring alignment over the candidate segments, or None below THRESHOLD."""
    aligned: list[tuple[float, _Searchable, int, int]] = []
    for candidate in candidates:
        alignment = fuzz.partial_ratio_alignment(folded, candidate.folded, score_cutoff=THRESHOLD)
        if alignment is not None:
            aligned.append((alignment.score, candidate, alignment.dest_start, alignment.dest_end))
    if not aligned:
        return None

    # `max` keeps the first of equal scores, and the candidates lead with the hint.
    score, candidate, dest_start, dest_end = max(aligned, key=lambda hit: hit[0])
    start, end = to_original(candidate.offsets, dest_start, dest_end)
    start, end = whole_words(candidate.segment.text, start, end)
    span = _span_at(source, candidate.segment.number, start, end)
    return Match(span=span, confidence=score / 100, method="fuzzy", needs_review=True)


def _span_at(source: Source, segment: int, start: int, end: int) -> Span:
    """Build a span from offsets into the segment text, after pulling its edges off space."""
    start, end = trim(source.segment_text(segment), start, end)
    return Span.of(source, segment, start, end)
