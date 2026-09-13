"""What was read, and the verbatim regions that point into it.

A source is frozen at ingest: `segments[i].text` is the sole coordinate system for
every span that will ever point into it, and `text_hash` names that text layer, so
a reparse that moved the offsets is caught instead of silently shifting every
stored span. A segment is whatever unit the reader produced -- a page, a paragraph,
a window -- so nothing but its number is modelled here.
"""

from __future__ import annotations

import hashlib

from pydantic import Field, model_validator

from atlas.model.base import Frozen


class Segment(Frozen):
    """One numbered part of a source, in the text layer that spans are measured against."""

    number: int = Field(ge=1, description="1-based ordinal as produced by the reader")
    text: str


class Source(Frozen):
    """Something that was read, after its text layer has been fixed.

    The id names what was read; `text_hash` names the text that came out of it, and
    the two differ exactly when a reader change moved the offsets under stored spans.
    """

    id: str
    origin: str = Field(description="Path or URI the source was read from")
    segments: tuple[Segment, ...] = Field(min_length=1)
    meta: dict[str, str] = Field(default_factory=dict)

    @property
    def text_hash(self) -> str:
        """Hash of the text layer itself, which is what spans are measured against."""
        digest = hashlib.sha256()
        for segment in self.segments:
            digest.update(f"{segment.number}\x00{segment.text}\x00".encode())
        return digest.hexdigest()[:12]

    def segment_text(self, number: int) -> str:
        for segment in self.segments:
            if segment.number == number:
                return segment.text
        raise KeyError(f"{self.id} has no segment {number}")


class Span(Frozen):
    """A verbatim region of a source, located by character offsets.

    Offsets index `Source.segment_text(segment)`. `text` is stored alongside them so
    a span can be re-verified without loading the source, and so a drifted text
    layer is detectable rather than silently wrong.
    """

    source_id: str
    segment: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _offsets_span_the_text(self) -> Span:
        if self.end <= self.start:
            raise ValueError("span end must be greater than start")
        if self.end - self.start != len(self.text):
            raise ValueError("span offsets do not match the length of its text")
        return self

    @classmethod
    def of(cls, source: Source, segment: int, start: int, end: int) -> Span:
        """Cut a span out of a source, the only construction that cannot lie.

        The text is taken from the segment rather than supplied, so the offsets and
        the quote cannot disagree. Every producer of provenance should come through
        here; the plain constructor exists for deserialising what this one wrote.
        """
        text = source.segment_text(segment)[start:end]
        if not text:
            raise ValueError(f"empty span at {start}:{end} in segment {segment} of {source.id}")
        return cls(source_id=source.id, segment=segment, start=start, end=end, text=text)

    def covers(self, segment_text: str) -> bool:
        """Whether the span still cuts its own text out of this segment."""
        return segment_text[self.start : self.end] == self.text
