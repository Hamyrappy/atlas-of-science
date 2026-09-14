"""One place that decides what a dash, a quotation mark and a run of spaces are.

Two things fold text and they must not disagree: placing a quote in a source, which
needs a folded copy that still maps back onto the original offsets, and indexing a
node or a question, which needs comparable terms. When those were two private
implementations, a quote located through one normalisation was indexed through
another and a search missed a node whose span had been placed perfectly well.

So `fold` is the foundation -- offset-preserving, used by relocation -- and
`normalise` and `tokenise` are built on the same table above it. Nothing here
touches a stored text layer: these produce copies, and `Source.segments[i].text`
stays exactly as it was ingested.
"""

from __future__ import annotations

import re
import unicodedata

_FOLD = {
    **{ord(c): "-" for c in "‐‑‒–—―−"},
    **{ord(c): "'" for c in "‘’‚‛′´"},
    **{ord(c): '"' for c in "“”„‟″«»"},
}

_TERM = re.compile(r"\w+(?:[-']\w+)*")
"""A term keeps the hyphen and the apostrophe inside it, which is the whole reason
the folding table above is shared: "F-score", "F‑score" and "F–score" are one term."""


def fold(text: str) -> tuple[str, tuple[int, ...]]:
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


def normalise(text: str) -> str:
    """The comparable form of a text: compatibility forms, punctuation, case, whitespace.

    The same table `fold` uses, so a folded copy and a normalised one differ only in
    case and in compatibility forms -- never in what counts as one word.
    """
    folded, _ = fold(unicodedata.normalize("NFKC", text))
    return folded.casefold()


def tokenise(text: str) -> tuple[str, ...]:
    """The terms of a text, normalised: what an index stores and a question is cut into."""
    return tuple(_TERM.findall(normalise(text)))


def to_original(offsets: tuple[int, ...], start: int, end: int) -> tuple[int, int]:
    """Map a half-open range of folded offsets onto the original text."""
    return offsets[start], offsets[end - 1] + 1


def trim(text: str, start: int, end: int) -> tuple[int, int]:
    """Pull both edges of a range in off whitespace."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def whole_words(text: str, start: int, end: int) -> tuple[int, int]:
    """Complete the words a range cuts through.

    Alignment stops wherever the cheapest path does, routinely mid word, and half
    a word is worthless as provenance. An edge already on whitespace cuts no word.
    """
    start, end = trim(text, start, end)
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return start, end
