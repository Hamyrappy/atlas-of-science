"""A table into a Source, with each row rendered once and never rendered again.

An Atlas that can read a paper and not the table the paper's numbers came out of is
reading the wrong half of the science. A table is not prose, though, and pushing a CSV
through a text reader loses the one thing that makes it a table -- which column a value
was in.

So a row is rendered into one segment, in a fixed way, and the rendering **becomes the
text layer**: `column: value | column: value`. That single decision is what lets
everything else in this library work unchanged on tabular data. A cell's value is a
verbatim substring of its row, so a node built from it is bound to a real span by
`Span.of`, so it can be quoted, re-verified and superseded exactly as a node cut out of
a sentence can. Invariant 2 then applies to the rendering: it is fixed at ingest and
never produced again, because a second rendering that put the columns in another order
would move every offset under every stored span.

The header row is not a segment. It names the columns, which travel in `meta`, so a
mapping can be written against column names rather than positions -- a file that gains a
column at the front breaks a positional mapping silently and a named one loudly.
"""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

from pydantic import Field

from atlas.model import Frozen, Segment, Source
from atlas.steps import State, register

SEPARATOR = " | "
"""What goes between two cells of a rendered row. Part of the text layer, so changing it
changes `Source.text_hash` and invalidates every span ever cut from a table."""

ASSIGN = ": "
"""What goes between a column name and its value, for the same reason."""

COLUMNS = "columns"
"""The `meta` key the column names travel under, so a mapping is written against names."""


class IngestTableOptions(Frozen):
    """How the file is read. Nothing here changes a value; it changes how one is found."""

    delimiter: str = Field(",", min_length=1, max_length=1)
    encoding: str = Field("utf-8", min_length=1)


@register("ingest_table", requires=("inputs",), produces=("sources",),
          options=IngestTableOptions)
def ingest_table(state: State, options: IngestTableOptions) -> State:
    """Read every input of the run as a delimited table, one segment per row."""
    return {
        "sources": tuple(
            read_table(Path(path), delimiter=options.delimiter, encoding=options.encoding)
            for path in state["inputs"]
        )
    }


def read_table(path: Path, *, delimiter: str = ",", encoding: str = "utf-8") -> Source:
    """One table as a Source: the id hashes the bytes, the segments render the rows."""
    data = path.read_bytes()
    rows = list(csv.reader(io.StringIO(data.decode(encoding)), delimiter=delimiter))
    if not rows:
        raise ValueError(f"{path} holds no rows")
    header, body = rows[0], rows[1:]
    if not body:
        raise ValueError(f"{path} holds a header and no rows")
    return Source(
        id=hashlib.sha256(data).hexdigest()[:12],
        origin=str(path),
        segments=tuple(
            Segment(number=number, text=render(header, row))
            for number, row in enumerate(body, start=1)
        ),
        meta={COLUMNS: SEPARATOR.join(header), "title": path.name},
    )


def render(header: list[str], row: list[str]) -> str:
    """One row as the text every span cut from it will be measured against.

    Fixed, and therefore boring on purpose: columns in the order the file gives them, a
    value rendered exactly as it was read, and a column the row does not reach rendered
    as empty rather than dropped -- because a row that lost a column would shift the
    offsets of every column after it.
    """
    cells = [f"{name}{ASSIGN}{row[index] if index < len(row) else ''}"
             for index, name in enumerate(header)]
    return SEPARATOR.join(cells) + "\n"


def cell(source: Source, segment: int, column: str) -> tuple[int, int] | None:
    """Where a column's value is in a rendered row, or None if the row has no such column.

    Offsets rather than the value: a caller wanting the value has the text, and a caller
    wanting a span needs exactly this and must not compute it a second way.
    """
    columns = source.meta.get(COLUMNS, "").split(SEPARATOR)
    if column not in columns:
        return None
    text = source.segment_text(segment)
    prefix = f"{column}{ASSIGN}"
    # The column name is unique in a rendered row by construction, so finding its
    # assignment is enough; the value runs to the next separator or to the end.
    at = text.find(prefix)
    if at < 0:
        return None
    start = at + len(prefix)
    end = text.find(SEPARATOR, start)
    return (start, len(text.rstrip("\n")) if end < 0 else end)
