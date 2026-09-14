"""Tests for PDF ingest: what the text layer is, and what names it."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.steps import get
from atlas.steps.ingest_pdf import read_pdf

SEGMENT_LINES = (
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
    return build_pdf(SEGMENT_LINES)


@pytest.fixture
def pdf_path(pdf_bytes: bytes, tmp_path: Path) -> Path:
    path = tmp_path / "sample.pdf"
    path.write_bytes(pdf_bytes)
    return path


def test_read_pdf_extracts_every_page_in_order(pdf_path: Path) -> None:
    source = read_pdf(pdf_path)

    assert [segment.number for segment in source.segments] == [1, 2]
    assert source.origin == str(pdf_path)
    for number, lines in enumerate(SEGMENT_LINES, start=1):
        text = source.segment_text(number)
        positions = [text.find(line) for line in lines]
        assert -1 not in positions and positions == sorted(positions)
    assert SEGMENT_LINES[1][0] not in source.segment_text(1)


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
    described.write_bytes(build_pdf(SEGMENT_LINES, title="A Title", author="An Author"))

    assert read_pdf(described).meta == {"title": "A Title", "author": "An Author"}
    assert read_pdf(pdf_path).meta == {}


def test_the_step_reads_every_input_of_the_run(
    pdf_path: Path, tmp_path: Path, build_pdf: Callable[..., bytes]
) -> None:
    other = tmp_path / "other.pdf"
    other.write_bytes(build_pdf((("A different sentence entirely.",),)))

    state = get("ingest_pdf")({"inputs": (pdf_path, str(other))})

    assert [source.origin for source in state["sources"]] == [str(pdf_path), str(other)]
    assert len({source.id for source in state["sources"]}) == 2
