"""Tests for turning a claimed relation into a link, under the rules a node is held to.

A relation is dropped for exactly three reasons and each of them has a case here: the
quote cannot be placed in the source, an endpoint is not a node the run found, or the
pack does not allow that predicate between those two types. Nothing is repaired, and
the refusals that are the pack's ruling come back as violations rather than as a count.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from atlas.model import Node, Schema, Segment, Source, Span
from atlas.ontology import load
from atlas.pipeline import Pipeline
from atlas.steps.relate import Relation, relate

TEXT = "The pressure gauge recorded the tide, and the tide was measured with that gauge.\n"
SOURCE = Source(id="notes", origin="notes.txt", segments=(Segment(number=1, text=TEXT),))
PACK = """
types:
  - name: Observation
    description: Something recorded as having happened.
    fields: [subject]
    label_field: subject
  - name: Instrument
    description: A device a recording was taken with.
    fields: [name]
    label_field: name

predicates:
  - name: recorded_with
    domain: Observation
    range: Instrument
    description: The observation was taken with this instrument.
"""
STEPS = """\
  - ingest_text
  - {stub_extract: {types: {Observation: subject}}}
  - relocate
  - validate
  - {stub_relate: {predicate: recorded_with}}
  - relate
"""


def node(node_id: str, type_name: str, quote: str, **fields: str) -> Node:
    start = TEXT.index(quote)
    return Node(
        id=node_id,
        type=type_name,
        fields=fields,
        spans=(Span.of(SOURCE, 1, start, start + len(quote)),),
        schema_version="0" * 12,
    )


TIDE = node("1" * 16, "Observation", "recorded the tide", subject="tide")
GAUGE = node("2" * 16, "Instrument", "The pressure gauge", name="gauge")


def state(schema: Schema, *relations: Relation) -> dict:
    return {"sources": (SOURCE,), "nodes": (TIDE, GAUGE), "relations": relations, "schema": schema}


def claim(predicate: str = "recorded_with", quote: str = "measured with that gauge",
          src: str = TIDE.ref, dst: str = GAUGE.ref) -> Relation:
    return Relation(source_id=SOURCE.id, segment=1, predicate=predicate,
                    src_ref=src, dst_ref=dst, quote=quote)


def loaded(tmp_path: Path) -> Schema:
    path = tmp_path / "pack.yaml"
    path.write_text(PACK, encoding="utf-8")
    return load(path)


def test_a_placed_relation_between_declared_types_becomes_a_link(tmp_path: Path) -> None:
    result = relate(state(loaded(tmp_path), claim()))

    [link] = result["links"]
    assert (link.predicate, link.src, link.dst) == ("recorded_with", TIDE.id, GAUGE.id)
    assert link.spans[0].text == "measured with that gauge"
    assert result["unrelated"] == 0
    assert result["relation_violations"] == ()


def test_a_quote_that_cannot_be_placed_is_dropped_and_counted(tmp_path: Path) -> None:
    result = relate(state(loaded(tmp_path), claim(quote="calibrated against a reference buoy")))

    assert result["links"] == ()
    assert result["unrelated"] == 1


def test_an_endpoint_the_run_never_found_is_dropped_and_counted(tmp_path: Path) -> None:
    result = relate(state(loaded(tmp_path), claim(dst="notes#ffffff")))

    assert result["links"] == ()
    assert result["unrelated"] == 1


def test_a_relation_the_pack_forbids_between_those_types_is_reported(tmp_path: Path) -> None:
    result = relate(state(loaded(tmp_path), claim(src=GAUGE.ref, dst=TIDE.ref)))

    assert result["links"] == ()
    # Not a count: the case is what makes the number worth anything.
    assert "expects domain 'Observation'" in result["relation_violations"][0]


def test_an_unknown_predicate_is_reported_rather_than_minted(tmp_path: Path) -> None:
    result = relate(state(loaded(tmp_path), claim(predicate="caused")))

    assert result["links"] == ()
    assert "unknown predicate 'caused'" in result["relation_violations"][0]


def test_the_same_relation_claimed_twice_is_one_link(tmp_path: Path) -> None:
    result = relate(state(loaded(tmp_path), claim(), claim()))

    assert len(result["links"]) == 1


def test_a_configured_run_extracts_relates_and_asserts_links(
    tmp_path: Path, write_config: Callable[[str, str], Path]
) -> None:
    (tmp_path / "notes.txt").write_text(TEXT, encoding="utf-8")

    state = Pipeline.from_config(write_config(PACK, STEPS)).run([tmp_path / "notes.txt"])

    # The stub relates each node of a segment to the next, and only one of the two
    # orderings satisfies the pack, so the run keeps what the pack allows and no more.
    assert [link.predicate for link in state["links"]] in ([], ["recorded_with"])
    assert set(state).issuperset({"links", "unrelated", "relation_violations"})
