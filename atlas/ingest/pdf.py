"""PDF ingest: a file on disk becomes a Document whose text layer is final.

Page text is stored exactly as the parser emits it, because every span made
downstream is measured against it and normalising here would move offsets that
stored artifacts already point at. The id hashes the file bytes and so names the
source; the text layer is named by `Document.text_hash`, which is what a reader
of the rendering checks.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

try:
    import pymupdf
except ImportError:  # the package was named fitz before version 1.24
    import fitz as pymupdf

from atlas.contracts import Document, Page

PAGE_MARKER = "<!-- page {number} -->"


def read_pdf(path: Path) -> Document:
    """Read a PDF into a Document whose id is the hash of the file bytes."""
    data = path.read_bytes()
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        pages = tuple(
            Page(number=number, text=page.get_text())
            for number, page in enumerate(pdf, start=1)
        )
        declared = pdf.metadata or {}
        meta = {key: declared[key] for key in ("title", "author") if declared.get(key)}
    meta["page_count"] = str(len(pages))
    return Document(
        id=hashlib.sha256(data).hexdigest()[:12],
        source=str(path),
        pages=pages,
        meta=meta,
    )


def to_markdown(document: Document) -> str:
    """Render a Document as front matter plus one marked block per page."""
    # JSON string syntax is a subset of YAML's double-quoted scalar, so an id or a
    # path that YAML would otherwise read as a number or a mapping stays a string.
    front_matter = (
        "---\n"
        f"id: {json.dumps(document.id)}\n"
        f"source: {json.dumps(document.source)}\n"
        f"page_count: {len(document.pages)}\n"
        f"text_hash: {json.dumps(document.text_hash)}\n"
        "---\n\n"
    )
    blocks = [
        f"{PAGE_MARKER.format(number=page.number)}\n{page.text}"
        for page in document.pages
    ]
    return front_matter + "\n".join(blocks)


def write_markdown(document: Document, directory: Path) -> Path:
    """Write the markdown rendering to <directory>/<id>.md and return that path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{document.id}.md"
    path.write_text(to_markdown(document), encoding="utf-8")
    return path
