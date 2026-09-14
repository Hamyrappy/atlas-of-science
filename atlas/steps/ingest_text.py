"""Plain text into a Source, with the text layer fixed exactly as it was read.

`ingest_pdf` reads the one format the library happened to ship a reader for; a
directory of `.txt` and `.md` files is the other half of the same job, and everyone
who has one writes this module again -- identically, apart from the mistake that is
easy to make. The mistake is tidying the text on the way in: stripping a block,
collapsing a blank line, reflowing a wrapped paragraph. `Segment.text` is the sole
coordinate system of every span that will ever be cut from this source, so a tidied
text layer silently moves offsets that stored objects already point at. Nothing here
alters a character: the splits decide only where one segment ends and the next begins.

How a file is cut is an option because segmentation is a cost decision and not a
truth. Extraction is one model call per segment, so a blank line is usually the right
unit, a short document is better whole, and a document with no blank lines at all
needs a window to stop being one prompt.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from atlas.model import Segment, Source
from atlas.steps import State, register

_BREAK = re.compile(r"\n[ \t]*\n")

WINDOW = 2000
"""Characters per segment under `split: window`, which cuts on a count and not on a
word: a window is a budget, and a quote that straddles two of them is placed in one."""

TITLE_CHARS = 120
"""How much of the first segment is kept as a title; a heading is short, a paragraph is not."""


@register("ingest_text", requires=("inputs",), produces=("sources",))
def ingest_text(state: State, *, split: str = "blank-line", window: int = WINDOW) -> State:
    """Read every input of the run as text encoded in UTF-8."""
    return {
        "sources": tuple(
            read_text(Path(path), split=split, window=window) for path in state["inputs"]
        )
    }


def read_text(path: Path, *, split: str = "blank-line", window: int = WINDOW) -> Source:
    """One file as a Source: the id hashes the bytes read, the segments quote them."""
    data = path.read_bytes()
    segments = cut(data.decode("utf-8"), split=split, window=window)
    if not segments:
        raise ValueError(f"{path} holds no text")
    return Source(
        id=hashlib.sha256(data).hexdigest()[:12],
        origin=str(path),
        segments=tuple(
            Segment(number=number, text=text) for number, text in enumerate(segments, start=1)
        ),
        meta={"title": _title(segments[0]) or path.name},
    )


def cut(text: str, *, split: str = "blank-line", window: int = WINDOW) -> tuple[str, ...]:
    """Where the segments of a text end. Every piece returned is a verbatim slice of it.

    A piece holding nothing but whitespace is dropped -- it can carry no quote, and a
    segment number is not evidence of anything -- but a piece that is kept is kept whole,
    leading and trailing whitespace included.
    """
    if split == "whole":
        pieces = [text]
    elif split == "blank-line":
        pieces = _BREAK.split(text)
    elif split == "window":
        size = max(window, 1)
        pieces = [text[at : at + size] for at in range(0, len(text), size)]
    else:
        raise ValueError(f"unknown split {split!r}; known: blank-line, whole, window")
    return tuple(piece for piece in pieces if piece.strip())


def _title(text: str) -> str:
    """What to call the document: its first line, without the marks a heading is written with."""
    return text.splitlines()[0].strip().lstrip("#").strip()[:TITLE_CHARS].strip()
