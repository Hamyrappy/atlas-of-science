"""Tests for PDF ingest and the markdown rendering it writes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from atlas.contracts import Document, Span
from atlas.ingest import read_pdf, to_markdown, write_markdown

PAGE_LINES = (
    (
        "Photosynthesis converts light into chemical energy.",
        "Chlorophyll absorbs red and blue light.",
    ),
    (
        "The rate saturates above a threshold irradiance.",
        "Temperature shifts the saturation point.",
    ),
)


@pytest.fixture(scope="session")
def pdf_bytes(build_pdf: Callable[..., bytes]) -> bytes:
    return build_pdf(PAGE_LINES)


@pytest.fixture
def pdf_path(pdf_bytes: bytes, tmp_path: Path) -> Path:
    path = tmp_path / "sample.pdf"
    path.write_bytes(pdf_bytes)
    return path


def _page_body(markdown: str, number: int) -> tuple[str, int]:
    marker = f"<!-- page {number} -->\n"
    start = markdown.index(marker) + len(marker)
    end = markdown.find("<!-- page ", start)
    return (markdown[start:] if end == -1 else markdown[start:end]), start


def _front_matter(markdown: str) -> dict[str, object]:
    return yaml.safe_load(markdown.split("---\n", 2)[1])


def test_read_pdf_extracts_every_page_in_order(pdf_path: Path) -> None:
    document = read_pdf(pdf_path)

    assert [page.number for page in document.pages] == [1, 2]
    assert document.source == str(pdf_path)
    assert document.meta["page_count"] == "2"
    for number, lines in enumerate(PAGE_LINES, start=1):
        text = document.page_text(number)
        positions = [text.find(line) for line in lines]
        assert -1 not in positions and positions == sorted(positions)
    assert PAGE_LINES[1][0] not in document.page_text(1)


def test_id_is_stable_across_reads_of_the_same_bytes(pdf_bytes: bytes, tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    second = tmp_path / "elsewhere" / "b.pdf"
    second.parent.mkdir()
    first.write_bytes(pdf_bytes)
    second.write_bytes(pdf_bytes)

    assert read_pdf(first).id == read_pdf(second).id
    assert len(read_pdf(first).id) == 12


def test_different_bytes_give_a_different_id(
    pdf_path: Path, tmp_path: Path, build_pdf: Callable[..., bytes]
) -> None:
    other = tmp_path / "other.pdf"
    other.write_bytes(build_pdf((("A different sentence entirely.",),)))

    assert read_pdf(other).id != read_pdf(pdf_path).id


def test_meta_carries_title_and_author_only_when_declared(
    pdf_path: Path, tmp_path: Path, build_pdf: Callable[..., bytes]
) -> None:
    described = tmp_path / "described.pdf"
    described.write_bytes(build_pdf(PAGE_LINES, title="A Title", author="An Author"))

    assert read_pdf(described).meta["title"] == "A Title"
    assert read_pdf(described).meta["author"] == "An Author"
    assert "title" not in read_pdf(pdf_path).meta
    assert "author" not in read_pdf(pdf_path).meta


def test_markdown_keeps_the_page_markers_and_the_page_text(pdf_path: Path) -> None:
    document = read_pdf(pdf_path)
    markdown = to_markdown(document)

    for number in (1, 2):
        body, _ = _page_body(markdown, number)
        assert document.page_text(number) in body


def test_front_matter_parses_as_yaml_with_string_scalars(pdf_path: Path) -> None:
    document = read_pdf(pdf_path)

    assert _front_matter(to_markdown(document)) == {
        "id": document.id,
        "source": str(pdf_path),
        "page_count": 2,
    }
    numeric = Document(id="123456789012", source=str(pdf_path), pages=document.pages)
    assert _front_matter(to_markdown(numeric))["id"] == "123456789012"


def test_page_offsets_survive_the_markdown_rendering(pdf_path: Path) -> None:
    document = read_pdf(pdf_path)
    text = document.page_text(2)
    start = text.index(PAGE_LINES[1][1])
    span = Span(
        doc_id=document.id,
        page=2,
        start=start,
        end=start + len(PAGE_LINES[1][1]),
        text=PAGE_LINES[1][1],
    )

    markdown = to_markdown(document)
    _, body_start = _page_body(markdown, 2)

    assert markdown[body_start + span.start : body_start + span.end] == span.text


def test_write_markdown_names_the_file_after_the_document(pdf_path: Path, tmp_path: Path) -> None:
    document = read_pdf(pdf_path)
    written = write_markdown(document, tmp_path / "out")

    assert written == tmp_path / "out" / f"{document.id}.md"
    assert written.read_text(encoding="utf-8") == to_markdown(document)
