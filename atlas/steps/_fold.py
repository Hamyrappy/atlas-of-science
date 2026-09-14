"""A folded copy of a text that still maps back onto it, character by character.

Relaxing a search means searching something other than the text the offsets must come
from, so every relaxation here folds a copy and keeps the source offset of each
character it kept. That map is what lets a hit found on the folded copy come back as a
span that re-slices to exactly its own text in the original.
"""

from __future__ import annotations

_FOLD = {
    **{ord(c): "-" for c in "‐‑‒–—―−"},
    **{ord(c): "'" for c in "‘’‚‛′´"},
    **{ord(c): '"' for c in "“”„‟″«»"},
}


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
