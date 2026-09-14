"""Tests for plain-text ingest, where the one thing that must not happen is tidying.

Every span ever cut from a source is measured against the segment text stored here, so
the tests below are mostly one assertion in different clothes: what came out is what was
in the file, at the offsets it was at. The splits are tested for where they cut, never
for what they change, because they change nothing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.model import Span
from atlas.pipeline import Pipeline
from atlas.steps import get
from atlas.steps.ingest_text import IngestTextOptions, cut, ingest_text, read_text

PACK = "types: []\n"

TEXT = (
    "# Отчёт  о работе\n"
    "\n"
    "Разработана  модель прогнозирования отказов.   \n"
    "Точность на выборке составила 0,94.\n"
    "\n"
    "   \n"
    "The F-score reached 0.91 on held-out data.\n"
)


@pytest.fixture
def document(tmp_path: Path) -> Path:
    path = tmp_path / "report.md"
    path.write_text(TEXT, encoding="utf-8")
    return path


def test_a_blank_line_ends_a_segment(document: Path) -> None:
    source = read_text(document)

    assert [segment.number for segment in source.segments] == [1, 2, 3]
    assert source.segments[0].text == "# Отчёт  о работе"
    assert source.origin == str(document)


def test_the_text_of_a_segment_is_the_bytes_that_were_read(document: Path) -> None:
    """Not stripped, not reflowed, not collapsed: the run of spaces and the ragged end stay."""
    source = read_text(document)

    for segment in source.segments:
        assert segment.text in TEXT
    assert "Разработана  модель" in source.segments[1].text
    assert source.segments[1].text.endswith("отказов.   \nТочность на выборке составила 0,94.")


def test_a_span_cut_from_a_segment_reslices_to_its_own_text(document: Path) -> None:
    source = read_text(document)
    text = source.segment_text(2)
    start = text.index("модель")

    span = Span.of(source, 2, start, start + len("модель"))

    assert span.text == "модель"
    assert span.covers(text)


def test_whole_keeps_the_document_in_one_segment(document: Path) -> None:
    source = read_text(document, split="whole")

    assert len(source.segments) == 1
    assert source.segments[0].text == TEXT


def test_a_window_cuts_on_a_count_and_loses_nothing(document: Path) -> None:
    source = read_text(document, split="window", window=40)

    assert len(source.segments) > 1
    assert "".join(segment.text for segment in source.segments) == TEXT


def test_a_segment_of_whitespace_is_dropped_and_the_rest_is_untouched() -> None:
    assert cut("one\n\n   \n\ntwo") == ("one", "two")


def test_an_unknown_split_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="unknown split 'sentences'"):
        cut(TEXT, split="sentences")


def test_a_file_with_no_text_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n\n", encoding="utf-8")

    with pytest.raises(ValueError, match="holds no text"):
        read_text(empty)


def test_the_id_names_the_bytes_and_the_title_the_first_line(
    tmp_path: Path, document: Path
) -> None:
    copy = tmp_path / "elsewhere.md"
    copy.write_text(TEXT, encoding="utf-8")

    source, same = read_text(document), read_text(copy)

    assert source.id == same.id
    assert source.meta["title"] == "Отчёт  о работе"


def test_the_step_reads_every_input_of_the_run(document: Path) -> None:
    state = ingest_text({"inputs": (document, str(document))}, IngestTextOptions())

    assert len(state["sources"]) == 2
    assert get("ingest_text").produces == ("sources",)


def test_the_split_a_configuration_writes_reaches_every_input(document: Path) -> None:
    """Through the registry, as a file reaches it: the mapping is read into the model first."""
    state = get("ingest_text")({"inputs": (document,)}, {"split": "whole"})

    assert len(state["sources"][0].segments) == 1


def test_a_fourth_split_is_refused_when_the_file_is_read_and_the_three_are_named(
    write_config: Callable[[str, str], Path]
) -> None:
    """The check `cut` makes once a run is under way, moved to the reading of the file."""
    config = write_config(PACK, "  - {ingest_text: {split: sentences}}\n")

    with pytest.raises(ValueError, match=re.escape(
        "step 'ingest_text': option 'split': Input should be 'blank-line', 'whole' or 'window'"
    )) as refused:
        Pipeline.from_config(config)

    assert "pipeline.yaml" in str(refused.value)


def test_a_window_of_no_characters_is_refused_rather_than_floored_to_one() -> None:
    """A configuration says what it meant; `cut` keeps defending itself against its callers."""
    with pytest.raises(ValueError, match=re.escape("step 'ingest_text': option 'window':")):
        get("ingest_text").configure({"split": "window", "window": 0})

    assert cut("abc", split="window", window=0) == ("a", "b", "c")
