"""Tests for reading the markdown rendering back into a Document.

The rendering is the on-disk form of a Document, so the property under test is
that page text and page offsets come back exactly as they went out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.contracts import Document, Page
from atlas.ingest import read_markdown, to_markdown

PAGES = ("The task is to segment cells.\nWe introduce a model.\n", "The model reached 0.912.\n")


def write(tmp_path: Path, document: Document) -> Path:
    path = tmp_path / f"{document.id}.md"
    path.write_text(to_markdown(document), encoding="utf-8")
    return path


def document(*texts: str, doc_id: str = "4f3c2b1a9e8d") -> Document:
    pages = tuple(Page(number=number, text=text) for number, text in enumerate(texts, start=1))
    return Document(id=doc_id, source="corpus/paper.pdf", pages=pages)


def test_a_rendering_reads_back_into_the_same_pages(tmp_path: Path) -> None:
    original = document(*PAGES)

    restored = read_markdown(write(tmp_path, original))

    assert restored.id == original.id
    assert restored.source == original.source
    assert restored.pages == original.pages


@pytest.mark.parametrize(
    "text",
    ["", "no trailing newline", "several\n\n\nblank lines\n\n", "  leading and trailing  \n"],
    ids=["empty", "unterminated", "blank-lines", "padded"],
)
def test_page_text_survives_the_round_trip_character_for_character(
    text: str, tmp_path: Path
) -> None:
    restored = read_markdown(write(tmp_path, document(text, "a second page\n")))

    assert restored.page_text(1) == text


def test_a_page_whose_text_holds_a_marker_is_refused_rather_than_split(tmp_path: Path) -> None:
    path = write(tmp_path, document("text\n<!-- page 9 -->\nmore\n", "a second page\n"))

    with pytest.raises(ValueError, match="markers"):
        read_markdown(path)


def test_a_file_without_front_matter_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bare.md"
    path.write_text("<!-- page 1 -->\nsome text\n", encoding="utf-8")

    with pytest.raises(ValueError, match="front matter"):
        read_markdown(path)


def test_front_matter_without_an_id_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "anonymous.md"
    path.write_text('---\nsource: "a.pdf"\n---\n\n<!-- page 1 -->\ntext\n', encoding="utf-8")

    with pytest.raises(ValueError, match="document id"):
        read_markdown(path)


def test_a_rendering_without_page_markers_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "unmarked.md"
    path.write_text('---\nid: "abc123abc123"\n---\n\nplain prose\n', encoding="utf-8")

    with pytest.raises(ValueError, match="page markers"):
        read_markdown(path)


def test_an_id_that_looks_numeric_stays_a_string(tmp_path: Path) -> None:
    restored = read_markdown(write(tmp_path, document(*PAGES, doc_id="123456789012")))

    assert restored.id == "123456789012"
