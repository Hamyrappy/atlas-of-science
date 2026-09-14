"""PDF ingest: a file on disk becomes a Source whose text layer is final.

Segment text is stored exactly as the parser emits it, because every span made
downstream is measured against it and normalising here would move offsets that
stored objects already point at. The id hashes the file bytes and so names what was
read; the text that came out of it is named by `Source.text_hash`, which is what a
reader of a rendering checks.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

try:
    import pymupdf
except ImportError:  # the package was named fitz before version 1.24
    import fitz as pymupdf

from atlas.model import Segment, Source
from atlas.steps import State, register


@register("ingest_pdf", requires=("inputs",), produces=("sources",))
def ingest_pdf(state: State) -> State:
    """Read every input of the run as a PDF."""
    return {"sources": tuple(read_pdf(Path(path)) for path in state["inputs"])}


def read_pdf(path: Path) -> Source:
    """Read a PDF into a Source whose id is the hash of the file bytes, one segment per page."""
    data = path.read_bytes()
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        segments = tuple(
            Segment(number=number, text=page.get_text())
            for number, page in enumerate(pdf, start=1)
        )
        declared = pdf.metadata or {}
        meta = {key: declared[key] for key in ("title", "author") if declared.get(key)}
    return Source(
        id=hashlib.sha256(data).hexdigest()[:12],
        origin=str(path),
        segments=segments,
        meta=meta,
    )
