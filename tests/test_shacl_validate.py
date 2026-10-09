"""Tests for validating a run's record against SHACL before it is written.

Under test: a node the shapes refuse is removed with every relation touching it; a
relation that breaks a range check is removed and its ends kept; a relation reaching a node
already in the store is checked against that node as stored, and the stored node is never
refused; a warning keeps its object; and `refuse: false` reports without removing.
"""

from __future__ import annotations

from atlas.model import Agent, Assertion, Link, Node, Segment, Source, Span
from atlas.ontology import load
from atlas.steps.shacl_validate import ShaclOptions, refused_by, shacl_validate
from atlas.store.memory import MemoryStore

TEXT = "Line A supports the claim that M raises yield; dataset D was archived."
SOURCE = Source(id="s1", origin="s.txt", segments=(Segment(number=1, text=TEXT),))
SCHEMA = load("science_core_rl", shapes=["science_core"])


def node(node_id: str, type_name: str, **fields: str) -> Node:
    return Node(id=node_id, type=type_name, fields=fields,
                spans=(Span.of(SOURCE, 1, 0, 6),), schema_version=SCHEMA.version)


def link(link_id: str, predicate: str, src: str, dst: str) -> Link:
    return Link(id=link_id, predicate=predicate, src=src, dst=dst,
                spans=(Span.of(SOURCE, 1, 7, 15),), schema_version=SCHEMA.version)


def run(nodes, links=(), store=None, **options) -> dict:  # noqa: ANN001
    state = {"nodes": tuple(nodes), "links": tuple(links), "schema": SCHEMA}
    if store is not None:
        state["store"] = store
    return shacl_validate(state, ShaclOptions(**options))


def test_a_refused_node_goes_and_takes_its_relations_with_it() -> None:
    line = node("line", "EvidenceLine", summary="rise")
    claim = node("claim", "Proposition", expression="x", colour="red")

    result = run([line, claim], [link("l", "supports", "line", "claim")])

    assert [one.id for one in result["nodes"]] == ["line"]
    assert result["links"] == ()
    assert not result["shacl_conforms"]
    assert "claim" in refused_by(result["shacl_violations"])


def test_a_relation_that_breaks_a_range_check_goes_and_its_ends_stay() -> None:
    line = node("line", "EvidenceLine", summary="rise")
    data = node("data", "Dataset", name="D")

    result = run([line, data], [link("l", "supports", "line", "data")])

    assert {one.id for one in result["nodes"]} == {"line", "data"}
    assert result["links"] == ()
    assert set(refused_by(result["shacl_violations"])) == {"l"}


def test_a_relation_to_a_stored_node_is_checked_against_it_and_it_is_never_refused() -> None:
    store = MemoryStore()
    store.add_source(SOURCE)
    stored = node("claim", "Proposition", expression="x", colour="red")  # itself invalid
    store.assert_(Assertion(id="a", agent=Agent(id="run", kind="run"),
                            at="2026-01-01T00:00:00+00:00", target=stored))
    line = node("line", "EvidenceLine", summary="rise")

    result = run([line], [link("l", "supports", "line", "claim")], store=store)

    # The range check saw the stored proposition; its own undeclared field is not this
    # run's to refuse.
    assert [one.id for one in result["links"]] == ["l"]
    assert result["shacl_conforms"]


def test_a_warning_is_reported_and_keeps_its_object() -> None:
    result = run([node("line", "EvidenceLine", summary="rise")])

    assert [one.id for one in result["nodes"]] == ["line"]
    assert any(one.severity == "warning" for one in result["shacl_violations"])
    assert result["shacl_conforms"]


def test_without_refusal_everything_is_kept_and_reported() -> None:
    claim = node("claim", "Proposition", expression="x", colour="red")

    result = run([claim], refuse=False)

    assert [one.id for one in result["nodes"]] == ["claim"]
    assert result["shacl_violations"]
