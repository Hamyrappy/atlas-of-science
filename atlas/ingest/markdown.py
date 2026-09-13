"""Reading back the markdown rendering that ingest writes.

Extraction runs against a file on disk, and the markdown rendering is the
on-disk form of a Document. Page text is restored exactly as it was written,
under the id it was ingested with, so a span located in a restored document
indexes the same coordinate system as one located right after ingest.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from atlas.contracts import Document, Page

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n\n", re.DOTALL)
_MARKER = re.compile(r"^<!-- page (\d+) -->\n", re.MULTILINE)


def read_markdown(path: Path) -> Document:
    """Read a markdown rendering written by `write_markdown` back into a Document."""
    text = path.read_text(encoding="utf-8")
    front_matter = _FRONT_MATTER.match(text)
    if front_matter is None:
        raise ValueError(f"{path} does not start with ingest front matter")
    header = _header(front_matter.group(1))
    if "id" not in header:
        raise ValueError(f"{path} declares no document id")
    pages = _pages(text[front_matter.end() :])
    if not pages:
        raise ValueError(f"{path} has no page markers")
    return Document(
        id=header["id"],
        source=header.get("source") or str(path),
        pages=pages,
        meta={"page_count": str(len(pages))},
    )


def _header(block: str) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in block.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            header[key.strip()] = _scalar(value.strip())
    return header


def _scalar(value: str) -> str:
    """Undo the double quoting that ingest applies to ids and paths."""
    return json.loads(value) if value.startswith('"') else value


def _pages(body: str) -> tuple[Page, ...]:
    markers = list(_MARKER.finditer(body))
    pages: list[Page] = []
    for index, marker in enumerate(markers):
        last = index + 1 == len(markers)
        text = body[marker.end() : len(body) if last else markers[index + 1].start()]
        # Every block but the last carries the newline that joined it to the next one.
        if not last:
            text = text.removesuffix("\n")
        pages.append(Page(number=int(marker.group(1)), text=text))
    return tuple(pages)
