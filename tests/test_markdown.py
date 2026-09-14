"""Tests for the markdown rendering of a source and for reading it back.

The rendering is the on-disk form of a Source, so the properties under test are that
segment text and segment offsets come back exactly as they went out, and that a file
someone has edited since is refused rather than read.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from atlas.model import Segment, Source, Span
from atlas.steps import get
from atlas.steps.markdown import read_markdown, to_markdown, write_markdown

TEXTS = ("The task is to segment cells.\nWe introduce a model.\n", "The model reached 0.912.\n")


def source(*texts: str, source_id: str = "4f3c2b1a9e8d") -> Source:
    segments = tuple(Segment(number=n, text=text) for n, text in enumerate(texts, start=1))
    return Source(id=source_id, origin="corpus/paper.pdf", segments=segments)


def write(tmp_path: Path, value: Source) -> Path:
    path = tmp_path / f"{value.id}.md"
    path.write_text(to_markdown(value), encoding="utf-8")
    return path


def _segment_body(markdown: str, number: int) -> tuple[str, int]:
    marker = f"<!-- segment {number} -->\n"
    start = markdown.index(marker) + len(marker)
    end = markdown.find("<!-- segment ", start)
    return (markdown[start:] if end == -1 else markdown[start:end]), start


def test_the_rendering_keeps_the_markers_and_the_segment_text() -> None:
    original = source(*TEXTS)
    markdown = to_markdown(original)

    for number in (1, 2):
        body, _ = _segment_body(markdown, number)
        assert original.segment_text(number) in body


def test_front_matter_parses_as_yaml_with_string_scalars() -> None:
    original = source(*TEXTS)

    assert yaml.safe_load(to_markdown(original).split("---\n", 2)[1]) == {
        "id": original.id,
        "origin": "corpus/paper.pdf",
        "segments": 2,
        "text_hash": original.text_hash,
    }
    numeric = source(*TEXTS, source_id="123456789012")
    assert yaml.safe_load(to_markdown(numeric).split("---\n", 2)[1])["id"] == "123456789012"


def test_segment_offsets_survive_the_rendering() -> None:
    original = source(*TEXTS)
    quote = "The model reached"
    start = original.segment_text(2).index(quote)
    span = Span.of(original, 2, start, start + len(quote))

    markdown = to_markdown(original)
    _, body_start = _segment_body(markdown, 2)

    assert markdown[body_start + span.start : body_start + span.end] == span.text


def test_write_markdown_names_the_file_after_the_source(tmp_path: Path) -> None:
    original = source(*TEXTS)

    written = write_markdown(original, tmp_path / "out")

    assert written == tmp_path / "out" / f"{original.id}.md"
    assert written.read_text(encoding="utf-8") == to_markdown(original)


def test_a_rendering_reads_back_into_the_same_segments(tmp_path: Path) -> None:
    original = source(*TEXTS)

    restored = read_markdown(write(tmp_path, original))

    assert restored.id == original.id
    assert restored.origin == original.origin
    assert restored.segments == original.segments
    assert restored.text_hash == original.text_hash


@pytest.mark.parametrize(
    "text",
    ["", "no trailing newline", "several\n\n\nblank lines\n\n", "  leading and trailing  \n"],
    ids=["empty", "unterminated", "blank-lines", "padded"],
)
def test_segment_text_survives_the_round_trip_character_for_character(
    text: str, tmp_path: Path
) -> None:
    restored = read_markdown(write(tmp_path, source(text, "a second segment\n")))

    assert restored.segment_text(1) == text


def test_a_segment_whose_text_holds_a_marker_is_refused_rather_than_split(tmp_path: Path) -> None:
    path = write(tmp_path, source("text\n<!-- segment 9 -->\nmore\n", "a second segment\n"))

    with pytest.raises(ValueError, match="markers"):
        read_markdown(path)


def test_a_file_without_front_matter_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bare.md"
    path.write_text("<!-- segment 1 -->\nsome text\n", encoding="utf-8")

    with pytest.raises(ValueError, match="front matter"):
        read_markdown(path)


def test_front_matter_without_an_id_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "anonymous.md"
    path.write_text('---\norigin: "a.pdf"\n---\n\n<!-- segment 1 -->\ntext\n', encoding="utf-8")

    with pytest.raises(ValueError, match="source id"):
        read_markdown(path)


def test_a_rendering_without_markers_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "unmarked.md"
    path.write_text('---\nid: "abc123abc123"\n---\n\nplain prose\n', encoding="utf-8")

    with pytest.raises(ValueError, match="segment markers"):
        read_markdown(path)


def test_an_id_that_looks_numeric_stays_a_string(tmp_path: Path) -> None:
    restored = read_markdown(write(tmp_path, source(*TEXTS, source_id="123456789012")))

    assert restored.id == "123456789012"


def test_an_edited_rendering_is_refused(tmp_path: Path) -> None:
    """An edit to a stored rendering moves the offsets under spans already written."""
    path = write(tmp_path, source(*TEXTS))
    path.write_text(
        path.read_text(encoding="utf-8").replace("cells", "cel ls"), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="no longer matches"):
        read_markdown(path)


def test_the_two_steps_write_and_read_the_same_sources(tmp_path: Path) -> None:
    written = get("render_markdown")({"sources": (source(*TEXTS),)}, {"out": str(tmp_path / "out")})

    restored = get("ingest_markdown")({"inputs": written["renderings"]})

    assert restored["sources"] == (source(*TEXTS),)


def test_a_rendering_with_nowhere_to_go_is_refused_when_the_file_is_read() -> None:
    """`out` is required, so a configuration that forgot it is wrong on the page rather
    than a TypeError raised after every source of the run has been read."""
    with pytest.raises(ValueError, match=re.escape(
        "step 'render_markdown': option 'out' is required. It takes out: str"
    )):
        get("render_markdown").configure(None)

    with pytest.raises(ValueError, match=re.escape("unknown option 'dir'")):
        get("render_markdown").configure({"dir": "renderings"})


def test_reading_a_rendering_takes_no_options_and_refuses_the_one_writing_it_takes() -> None:
    with pytest.raises(ValueError, match=re.escape(
        "step 'ingest_markdown': unknown option 'out'. It takes no options"
    )):
        get("ingest_markdown").configure({"out": "renderings"})
