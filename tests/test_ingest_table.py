"""Tests for reading a table, where the rendering of a row becomes the text layer.

The whole architecture of tabular reading rests on one decision: a row is rendered once,
the rendering is what spans are measured against, and it is never produced a second way.
So the tests are about that -- a value is a verbatim substring of its row, a missing cell
does not shift the columns after it, and the header travels in `meta` so a mapping is
written against names rather than positions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.model import Span
from atlas.steps.ingest_table import (
    COLUMNS,
    IngestTableOptions,
    cell,
    ingest_table,
    read_table,
    render,
)

ROWS = (
    "study,outcome,value,unit\n"
    "S-1,yield rose,0.94,fraction\n"
    "S-2,no change,0.02,fraction\n"
)


@pytest.fixture
def table(tmp_path: Path) -> Path:
    path = tmp_path / "results.csv"
    path.write_text(ROWS, encoding="utf-8")
    return path


def test_each_row_becomes_one_segment_and_the_header_does_not(table: Path) -> None:
    source = read_table(table)

    assert len(source.segments) == 2
    assert source.meta[COLUMNS] == "study | outcome | value | unit"


def test_a_value_is_a_verbatim_substring_of_its_own_row(table: Path) -> None:
    source = read_table(table)

    where = cell(source, 1, "value")

    assert where is not None
    span = Span.of(source, 1, *where)
    assert span.text == "0.94"


def test_a_span_cut_from_a_row_re_slices_to_its_own_text(table: Path) -> None:
    source = read_table(table)
    where = cell(source, 2, "outcome")

    span = Span.of(source, 2, *where)

    assert span.covers(source.segment_text(2))


def test_the_last_column_runs_to_the_end_of_the_row(table: Path) -> None:
    source = read_table(table)

    where = cell(source, 1, "unit")

    assert Span.of(source, 1, *where).text == "fraction"


def test_a_column_the_table_does_not_have_is_not_found(table: Path) -> None:
    assert cell(read_table(table), 1, "pressure") is None


def test_a_row_short_of_a_column_renders_it_empty_rather_than_dropping_it() -> None:
    # Dropping it would shift the offsets of every column after it.
    rendered = render(["a", "b", "c"], ["1", "2"])

    assert rendered == "a: 1 | b: 2 | c: \n"


def test_two_reads_of_one_file_give_one_text_layer(table: Path) -> None:
    first, second = read_table(table), read_table(table)

    assert first.text_hash == second.text_hash
    assert first.id == second.id


def test_a_table_with_no_rows_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("a,b\n", encoding="utf-8")

    with pytest.raises(ValueError, match="header and no rows"):
        read_table(path)


def test_the_step_reads_every_input(table: Path) -> None:
    state = ingest_table({"inputs": (table,)}, IngestTableOptions())

    assert len(state["sources"]) == 1
    assert state["sources"][0].origin == str(table)


def test_another_delimiter_is_an_option(tmp_path: Path) -> None:
    path = tmp_path / "semis.csv"
    path.write_text("a;b\n1;2\n", encoding="utf-8")

    source = read_table(path, delimiter=";")

    assert source.segment_text(1) == "a: 1 | b: 2\n"
