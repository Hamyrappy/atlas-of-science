"""What more than one test module needs: a PDF, a configuration, stubs, and a small graph.

The PDF is built here rather than committed, so the suite carries no binary and the
text layer under test is the one this machine's parser produces. The stubs stand in
for the two steps that would need a model, and are registered under names like any
other step: several modules run the same configured pipeline over different packs,
which is the claim the library makes about itself.

The `science` fixture is the other half. Fifteen architectures are built on walking a
graph, and every test of one of them needs the same thing to walk: one claim, a
position for it, a position against it, the results and conditions behind each, and the
computation one of them came out of. Writing that out fifteen times would have made the
tests agree by accident; writing it once here makes them disagree visibly when they
disagree at all.
"""

from __future__ import annotations

import hashlib
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pymupdf
import pytest

from atlas.model import Agent, Assertion, Frozen, Link, Node, Schema, Segment, Source, Span
from atlas.ontology import load
from atlas.steps import State, register
from atlas.steps.relate import Relation
from atlas.steps.relocate import Statement
from atlas.store.memory import MemoryStore


@pytest.fixture(scope="session")
def build_pdf() -> Callable[..., bytes]:
    """A function turning one tuple of lines per page, plus optional metadata, into PDF bytes."""

    def build(lines_per_page: tuple[tuple[str, ...], ...], **metadata: str) -> bytes:
        pdf = pymupdf.open()
        for lines in lines_per_page:
            page = pdf.new_page()
            page.insert_text((72, 72), list(lines), fontsize=11)
        if metadata:
            pdf.set_metadata(metadata)
        return pdf.tobytes()

    return build


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[[str, str], Path]:
    """A function writing a pack and a configuration naming it, returning the configuration."""

    def write(pack: str, steps: str) -> Path:
        (tmp_path / "pack.yaml").write_text(pack, encoding="utf-8")
        path = tmp_path / "pipeline.yaml"
        path.write_text(f"schema: pack.yaml\nsteps:\n{textwrap.dedent(steps)}", encoding="utf-8")
        return path

    return write


class StubExtractOptions(Frozen):
    """The vocabulary the stub invents statements for: a type name to the field it fills."""

    types: dict[str, str] = {"Thing": "name"}


@register("stub_extract", requires=("sources",), produces=("statements", "malformed"),
          options=StubExtractOptions)
def stub_extract(state: State, options: StubExtractOptions) -> State:
    """Stand in for a model: one statement per segment per configured type and field."""
    statements: list[Statement] = []
    for source in state["sources"]:
        for segment in source.segments:
            quote = segment.text.splitlines()[0]
            statements += [
                Statement(
                    source_id=source.id,
                    segment=segment.number,
                    type=name,
                    fields={field: quote},
                    quote=quote,
                )
                for name, field in options.types.items()
            ]
    return {"statements": tuple(statements), "malformed": 0}


class StubRelateOptions(Frozen):
    """Which relation the stub claims, and nothing else: one predicate over each adjacent pair."""

    predicate: str = "related_to"


@register("stub_relate", requires=("sources", "nodes"),
          produces=("relations", "malformed_relations"), options=StubRelateOptions)
def stub_relate(state: State, options: StubRelateOptions) -> State:
    """Stand in for a relation extractor: relate each node of a segment to the next one."""
    relations: list[Relation] = []
    for source in state["sources"]:
        for segment in source.segments:
            here = [
                node for node in state["nodes"]
                if any(s.source_id == source.id and s.segment == segment.number
                       for s in node.spans)
            ]
            quote = segment.text.splitlines()[0]
            relations += [
                Relation(source_id=source.id, segment=segment.number,
                         predicate=options.predicate, src_ref=src.ref, dst_ref=dst.ref,
                         quote=quote)
                for src, dst in zip(here, here[1:], strict=False)
            ]
    return {"relations": tuple(relations), "malformed_relations": 0}


#: A small body of scientific markup, shaped like `packs/science_core.yaml`: one claim,
#: a position for it and a position against it, the results each rests on, the conditions
#: they were observed under, and the computation one of them came out of. Small enough to
#: read in a failure message and large enough that a walk of two hops has somewhere to go.
LINES = (
    "Treatment M raised the measured yield under conditions U1.",
    "Under conditions U2 the same effect was not detected in any run.",
    "The yield rose to 0.94 in the first series of experiments.",
    "The second series recorded no change beyond 0.02 of the control.",
    "Both series were analysed with the same script, revision 7, over the 2024 archive.",
)

#: Each node of that body: the type it is, the fields it fills, and the segment and quote
#: it was taken from. Written out rather than extracted, because a fixture that depended
#: on an extractor would fail for two reasons at once.
MARKUP = (
    ("claim", "Proposition", {"expression": "M raises yield"}, 1,
     "Treatment M raised the measured yield"),
    ("for", "Statement", {"text": "the first series supports it", "direction": "supports"}, 3,
     "The yield rose to 0.94"),
    ("against", "Statement", {"text": "the second series does not", "direction": "disputes"}, 4,
     "recorded no change beyond 0.02"),
    ("line-for", "EvidenceLine", {"summary": "rise observed", "direction": "supports"}, 3,
     "The yield rose to 0.94 in the first series"),
    ("line-against", "EvidenceLine", {"summary": "no effect observed", "direction": "disputes"}, 2,
     "the same effect was not detected"),
    ("result-1", "StudyResult", {"statement": "yield 0.94", "value": "0.94"}, 3,
     "rose to 0.94"),
    ("result-2", "StudyResult", {"statement": "no change", "value": "0.02"}, 4,
     "no change beyond 0.02"),
    ("u1", "Context", {"description": "U1", "conditions": "U1"}, 1, "conditions U1"),
    ("u2", "Context", {"description": "U2", "conditions": "U2"}, 2, "conditions U2"),
    ("run", "Computation", {"name": "analysis", "version": "7"}, 5, "the same script, revision 7"),
    ("archive", "Dataset", {"name": "archive", "version": "2024"}, 5, "the 2024 archive"),
)

#: How those nodes stand to each other, by the keys above.
WIRING = (
    ("for", "states", "claim", 3),
    ("against", "states", "claim", 4),
    ("for", "has_evidence_line", "line-for", 3),
    ("against", "has_evidence_line", "line-against", 4),
    ("line-for", "supports", "claim", 3),
    ("line-against", "disputes", "claim", 2),
    ("line-for", "rests_on", "result-1", 3),
    ("line-against", "rests_on", "result-2", 4),
    ("result-1", "observed_under", "u1", 1),
    ("result-2", "observed_under", "u2", 2),
    ("result-1", "derived_from", "run", 5),
    ("run", "used_dataset", "archive", 5),
    ("u1", "comparable_with", "u2", 2),
)


class Fixture(NamedTuple):
    """A store holding the small body of markup, the schema it was written under, its parts."""

    store: MemoryStore
    schema: Schema
    source: Source
    nodes: dict[str, Node]
    links: dict[str, Link]


@pytest.fixture
def science() -> Fixture:
    """The small body of markup above, asserted into a store under the shipped science pack."""
    schema = load("science_core")
    source = Source(
        id="paper-1",
        origin="corpus/paper-1.txt",
        segments=tuple(Segment(number=n, text=line) for n, line in enumerate(LINES, start=1)),
    )
    nodes: dict[str, Node] = {}
    for key, type_name, fields, segment, quote in MARKUP:
        start = source.segment_text(segment).index(quote)
        nodes[key] = Node(
            id=hashlib.sha256(key.encode()).hexdigest()[:16],
            type=type_name,
            fields=fields,
            spans=(Span.of(source, segment, start, start + len(quote)),),
            schema_version=schema.version,
        )
    links: dict[str, Link] = {}
    for src, predicate, dst, segment in WIRING:
        text = source.segment_text(segment)
        links[f"{src}-{predicate}-{dst}"] = Link.of(
            predicate=predicate,
            src=nodes[src].id,
            dst=nodes[dst].id,
            spans=(Span.of(source, segment, 0, len(text.rstrip())),),
            schema_version=schema.version,
        )
    store = MemoryStore()
    store.add_source(source)
    store.add_schema(schema)
    agent = Agent(id="fixture", kind="run")
    for index, target in enumerate([*nodes.values(), *links.values()]):
        store.assert_(Assertion(id=f"a{index:03d}", agent=agent, at="2026-01-01T00:00:00+00:00",
                                target=target))
    return Fixture(store, schema, source, nodes, links)
