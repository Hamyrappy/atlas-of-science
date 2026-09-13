"""Tests for the pluggable ontology: term lookup, inheritance, and the two validators.

The schema here is invented for the test and shares nothing with the file shipped in
`atlas/ontology/`: the point of the metamodel is that it holds for any vocabulary.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas.model import FieldDef, Link, Node, PredicateDef, Schema, Segment, Source, Span, TypeDef

SOURCE = Source(id="src-1", origin="a.pdf", segments=(Segment(number=1, text="a verbatim quote"),))
VERSION = "0" * 12

SCHEMA = Schema(
    version=VERSION,
    prefixes={"ex": "https://example.org/terms#"},
    types=(
        TypeDef(name="Thing", iri="ex:Thing", fields=(FieldDef(name="name"),)),
        TypeDef(
            name="Measure",
            iri="https://example.org/terms#Measure",
            parent="Thing",
            fields=(FieldDef(name="value", datatype="decimal"),),
            mappings=("skos:exactMatch qudt:Quantity",),
        ),
        TypeDef(name="Place", parent="Thing"),
        TypeDef(name="Event"),
    ),
    predicates=(
        PredicateDef(name="about", iri="ex:about", domain="Thing", range="Place"),
        PredicateDef(name="measures", domain="Measure", range="Thing"),
    ),
)


def span(text: str = "a verbatim quote") -> Span:
    return Span(source_id=SOURCE.id, segment=1, start=0, end=len(text), text=text)


def node(type_name: str, fields: dict[str, str], spans: tuple[Span, ...] = ()) -> Node:
    return Node(
        id="node-1",
        type=type_name,
        fields=fields,
        spans=spans or (span(),),
        schema_version=VERSION,
    )


def link(predicate: str) -> Link:
    return Link.of(predicate, "node-1", "node-2", (span(),), VERSION)


def test_a_term_is_found_by_name_by_iri_and_by_curie() -> None:
    by_name = SCHEMA.find_type("Measure")

    assert by_name is not None
    assert SCHEMA.find_type("ex:Measure") is by_name
    assert SCHEMA.find_type("https://example.org/terms#Measure") is by_name
    assert SCHEMA.find_type("ex:Thing") is SCHEMA.find_type("Thing")
    assert SCHEMA.find_predicate("https://example.org/terms#about") is SCHEMA.find_predicate(
        "about"
    )


def test_an_unknown_term_is_not_invented() -> None:
    assert SCHEMA.find_type("Instrument") is None
    assert SCHEMA.find_type("other:Thing") is None
    assert SCHEMA.find_predicate("nowhere") is None
    assert SCHEMA.ancestry("Instrument") == ()
    assert SCHEMA.declared_fields("Instrument") == ()


def test_type_names_are_the_local_labels() -> None:
    assert SCHEMA.type_names() == {"Thing", "Measure", "Place", "Event"}


def test_a_type_inherits_the_fields_of_its_ancestors_without_repeats() -> None:
    assert [f.name for f in SCHEMA.declared_fields("Measure")] == ["value", "name"]
    assert [t.name for t in SCHEMA.ancestry("Measure")] == ["Measure", "Thing"]
    assert SCHEMA.declared_fields("Measure")[0].datatype == "decimal"


def test_a_declared_field_is_not_repeated_by_a_subtype_that_redeclares_it() -> None:
    schema = SCHEMA.model_copy(
        update={
            "types": (
                SCHEMA.types[0],
                SCHEMA.types[1].model_copy(update={"fields": (FieldDef(name="name"),)}),
            )
        }
    )

    assert [f.name for f in schema.declared_fields("Measure")] == ["name"]


def test_a_parent_cycle_terminates_instead_of_hanging() -> None:
    schema = Schema(
        version=VERSION,
        types=(TypeDef(name="A", parent="B"), TypeDef(name="B", parent="A")),
    )

    assert [t.name for t in schema.ancestry("A")] == ["A", "B"]


def test_a_valid_node_passes_clean() -> None:
    assert SCHEMA.validate_node(node("Measure", {"value": "0.912", "name": "accuracy"})) == []
    assert SCHEMA.validate_node(node("ex:Measure", {"value": "0.912"})) == []


def test_an_unknown_type_is_reported() -> None:
    violations = SCHEMA.validate_node(node("Instrument", {}))

    assert len(violations) == 1
    assert "Instrument" in violations[0]


def test_an_undeclared_field_is_reported() -> None:
    violations = SCHEMA.validate_node(node("Place", {"name": "a place", "population": "3"}))

    assert len(violations) == 1
    assert "population" in violations[0]


def test_a_blank_span_is_reported() -> None:
    assert SCHEMA.validate_node(node("Place", {}, spans=(span("   "),))) != []


def test_links_are_checked_against_domain_and_range() -> None:
    assert SCHEMA.validate_link(link("about"), "Thing", "Place") == []
    assert SCHEMA.validate_link(link("ex:about"), "Measure", "Place") == []
    assert len(SCHEMA.validate_link(link("about"), "Event", "Event")) == 2
    assert len(SCHEMA.validate_link(link("nowhere"), "Thing", "Place")) == 1


def test_a_subtype_satisfies_the_domain_of_its_parent() -> None:
    assert SCHEMA.is_a("Measure", "Thing")
    assert not SCHEMA.is_a("Thing", "Measure")
    assert SCHEMA.validate_link(link("measures"), "Measure", "Place") == []


def test_a_schema_refuses_an_undeclared_key() -> None:
    with pytest.raises(ValidationError):
        Schema(version=VERSION, namespace="ex:")
