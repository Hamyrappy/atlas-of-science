"""Turning rows into a typed graph through a mapping, and refusing to join on nothing.

A database of results is already structured, and copying it into prose so that a model
can extract it back out again is a way of introducing errors on purpose. What it needs
instead is a mapping: this column is the identity of a study, that one is the value of a
result, and the two are related. This step executes such a mapping, and produces the
same nodes and links every other architecture produces -- bound to verbatim spans of the
rendered row, because `ingest_table` made the rendering the text layer.

**The rule that carries the module: an empty key never joins.** A mapping identifies a
thing by the value of a column, and a row where that column is blank produces no node
and therefore no relation. It is tempting to let it through as the empty string, and the
result is catastrophic and quiet: every row missing that column collapses into one node,
and every relation touching it becomes a claim about a thing that does not exist. A row
that cannot be identified is counted in `unmapped` and skipped.

**A relation needs both ends in the same row.** Joining across rows means deciding which
rows belong together, which is a question about the data that nobody here can answer.
A mapping that wants it says so by producing a column that already carries the join.

**A node is minted once, from the first row that identifies it.** Its span is that row's,
so the evidence for a study named in forty rows is the row where it was first seen, and
the forty rows do not become forty nodes. A second row identifying the same thing is not
a second thing, and it is not a correction either -- if the fields differ, that is a
mapping to fix or an assertion to supersede, not something to average.
"""

from __future__ import annotations

import hashlib

from pydantic import Field

from atlas.model import Frozen, Link, Node, Schema, Source, Span
from atlas.steps import State, register
from atlas.steps.ingest_table import cell


class NodeMapping(Frozen):
    """One kind of thing a row may produce: its type, what identifies it, what it says."""

    type: str = Field(min_length=1)
    key: str = Field(min_length=1, description="Column whose value identifies the thing")
    fields: dict[str, str] = Field(
        default_factory=dict, description="Field of the type to the column that fills it"
    )
    span: str = Field(
        default="", description="Column the node's evidence is cut from; the key by default"
    )


class LinkMapping(Frozen):
    """One relation a row may produce, between two things the same row identifies."""

    predicate: str = Field(min_length=1)
    src: str = Field(min_length=1, description="Name of the node mapping it runs from")
    dst: str = Field(min_length=1, description="Name of the node mapping it runs to")
    span: str = Field(default="", description="Column the relation's evidence is cut from")


class MapRowsOptions(Frozen):
    """The mapping: what a row produces, and how the pieces of it are related."""

    nodes: dict[str, NodeMapping] = Field(default_factory=dict)
    links: tuple[LinkMapping, ...] = ()


@register("map_rows", requires=("sources", "schema"),
          produces=("nodes", "links", "unmapped", "mapping_violations"),
          options=MapRowsOptions)
def map_rows(state: State, options: MapRowsOptions) -> State:
    """Execute the mapping over every row of every source, and report what it could not map."""
    schema: Schema = state["schema"]
    nodes: dict[str, Node] = {}
    links: dict[str, Link] = {}
    unmapped = 0
    violations: list[str] = []
    for source in state["sources"]:
        for segment in source.segments:
            made, missing = _row(source, segment.number, options, schema)
            unmapped += missing
            for name, node in made.items():
                nodes.setdefault(node.id, node)
                made[name] = nodes[node.id]
            for mapping in options.links:
                src, dst = made.get(mapping.src), made.get(mapping.dst)
                if src is None or dst is None:
                    # One end was not identified, so there is nothing to relate. The row
                    # that failed to identify it was already counted.
                    continue
                link = _link(source, segment.number, mapping, src, dst, schema)
                if link is None:
                    unmapped += 1
                    continue
                problems = schema.validate_link(link, src.type, dst.type)
                if problems:
                    violations += problems
                else:
                    links.setdefault(link.id, link)
    return {"nodes": tuple(nodes.values()), "links": tuple(links.values()),
            "unmapped": unmapped, "mapping_violations": tuple(violations)}


def identity(type_name: str, key: str) -> str:
    """The id a mapped thing gets, from its type and the value that identifies it.

    Stable across rows, files and runs, which is the whole point of a mapping: the same
    study named in two tables is one node, and it stays one node when the tables are
    read again next week.
    """
    return hashlib.sha256(f"{type_name}\x00{key}".encode()).hexdigest()[:16]


def _row(
    source: Source, number: int, options: MapRowsOptions, schema: Schema
) -> tuple[dict[str, Node], int]:
    """The nodes one row produces, and how many mappings it could not satisfy."""
    made: dict[str, Node] = {}
    missing = 0
    text = source.segment_text(number)
    for name, mapping in options.nodes.items():
        where = cell(source, number, mapping.key)
        key = text[where[0]:where[1]].strip() if where else ""
        # An empty key never joins. Letting it through would collapse every row missing
        # this column into one node and make every relation touching it a claim about a
        # thing that does not exist.
        if not key:
            missing += 1
            continue
        at = cell(source, number, mapping.span or mapping.key)
        if at is None or at[1] <= at[0]:
            missing += 1
            continue
        made[name] = Node(
            id=identity(mapping.type, key),
            type=mapping.type,
            fields=_fields(source, number, mapping),
            spans=(Span.of(source, number, *at),),
            schema_version=schema.version,
        )
    return made, missing


def _fields(source: Source, number: int, mapping: NodeMapping) -> dict[str, str]:
    """What the row says about the thing, by the columns the mapping names.

    A column the row leaves blank contributes nothing rather than an empty string: a
    field nobody filled and a field filled with nothing are different claims, and the
    second is the one that looks like data.
    """
    text = source.segment_text(number)
    found: dict[str, str] = {}
    for field, column in mapping.fields.items():
        where = cell(source, number, column)
        value = text[where[0]:where[1]].strip() if where else ""
        if value:
            found[field] = value
    return found


def _link(
    source: Source, number: int, mapping: LinkMapping, src: Node, dst: Node, schema: Schema
) -> Link | None:
    """The relation this row asserts, cut from the column the mapping points at.

    Where the mapping names no column, the evidence is the whole row: the relation is
    what the row's being one row says, and that is the honest span for it.
    """
    text = source.segment_text(number)
    at = cell(source, number, mapping.span) if mapping.span else (0, len(text.rstrip("\n")))
    if at is None or at[1] <= at[0]:
        return None
    return Link.of(
        predicate=mapping.predicate,
        src=src.id,
        dst=dst.id,
        spans=(Span.of(source, number, *at),),
        schema_version=schema.version,
    )
