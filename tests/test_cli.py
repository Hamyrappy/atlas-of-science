"""CLI tests: argument handling, exit codes and the files each subcommand writes.

The library runs for real, on a PDF built in a fixture; only the extraction call
itself is replaced, since it is the one step that would need a model.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from atlas.cli import main
from atlas.contracts import Card, Span
from atlas.extract import ExtractionResult
from atlas.ingest import read_pdf
from atlas.ingest.markdown import read_markdown

MODEL_VARIABLES = ("ATLAS_BASE_URL", "ATLAS_MODEL", "ATLAS_API_KEY")
PAGE_LINES = (
    ("Iron oxidises in damp air.", "The rate rises with temperature."),
    ("A coating of zinc delays the onset.",),
)


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    pdf = pymupdf.open()
    for lines in PAGE_LINES:
        page = pdf.new_page()
        page.insert_text((72, 72), list(lines), fontsize=11)
    path = tmp_path / "sample.pdf"
    path.write_bytes(pdf.tobytes())
    return path


def test_no_subcommand_prints_usage_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])

    assert code != 0
    assert "usage: atlas" in capsys.readouterr().err


def test_ingest_writes_a_markdown_file_and_reports_it(
    pdf_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "markdown"

    code = main(["ingest", str(pdf_path), "--out", str(out)])
    printed = capsys.readouterr().out

    document = read_pdf(pdf_path)
    written = out / f"{document.id}.md"
    assert code == 0
    assert written.exists()
    assert printed.splitlines() == [f"{document.id}\t2\t{written}"]


def test_ingest_reads_every_pdf_it_is_given(
    pdf_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    second = tmp_path / "second.pdf"
    second.write_bytes(pdf_path.read_bytes())

    code = main(["ingest", str(pdf_path), str(second), "--out", str(tmp_path / "markdown")])

    assert code == 0
    assert len(capsys.readouterr().out.splitlines()) == 2


@pytest.mark.parametrize("contents", [None, b"not a pdf"], ids=["missing", "unreadable"])
def test_ingest_reports_a_source_it_cannot_read_on_one_line(
    contents: bytes | None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.pdf"
    if contents is not None:
        source.write_bytes(contents)

    code = main(["ingest", str(source), "--out", str(tmp_path / "markdown")])

    assert code != 0
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_markdown_written_by_ingest_reads_back_with_the_same_pages(
    pdf_path: Path, tmp_path: Path
) -> None:
    out = tmp_path / "markdown"
    main(["ingest", str(pdf_path), "--out", str(out)])
    document = read_pdf(pdf_path)

    restored = read_markdown(out / f"{document.id}.md")

    assert restored.id == document.id
    assert restored.source == document.source
    assert [(page.number, page.text) for page in restored.pages] == [
        (page.number, page.text) for page in document.pages
    ]


def test_extract_without_the_model_environment_fails_on_one_line(
    pdf_path: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    for variable in MODEL_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    out = tmp_path / "cards.jsonl"

    code = main(["extract", str(pdf_path), "--out", str(out)])
    captured = capsys.readouterr()

    assert code != 0
    assert len(captured.err.splitlines()) == 1
    assert "ATLAS_BASE_URL" in captured.err
    assert not out.exists()


def test_extract_writes_one_card_per_line_and_reports_counts(
    pdf_path: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    for variable in MODEL_VARIABLES:
        monkeypatch.setenv(variable, "unused")
    document = read_pdf(pdf_path)
    quote = document.page_text(1)[:10]
    span = Span(doc_id=document.id, page=1, start=0, end=len(quote), text=quote)
    card = Card(
        id="0123456789abcdef", type="Claim", spans=(span,), run_id="run",
        ontology_version="0" * 12,
    )
    result = ExtractionResult(cards=(card,), dropped=2, needs_review=1)
    monkeypatch.setattr("atlas.cli.extract_cards", lambda *_, **__: result)
    out = tmp_path / "cards" / "cards.jsonl"

    code = main(["extract", str(pdf_path), "--out", str(out)])

    lines = out.read_text(encoding="utf-8").splitlines()
    written = Card.model_validate_json(lines[0])
    restored = written.spans[0]
    assert code == 0
    assert len(lines) == 1
    assert written == card
    assert document.page_text(restored.page)[restored.start : restored.end] == restored.text
    assert capsys.readouterr().out.splitlines() == ["cards 1\tdropped 2\tneeds review 1"]
