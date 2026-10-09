"""SHACL: what a record must carry, checked in closed world.

Under test: a field the class does not declare is refused; a node of a subclass is not
refused by the closed shape of its superclass; a relation whose subject is not recorded as
its domain is refused, even though OWL would simply infer the type; no node stands on
nothing; a warning keeps the object; and the shapes shipped for the science core catch a
computation that depends on itself through a chain, which OWL 2 DL cannot state.
"""

from __future__ import annotations

from atlas.model import Link, Node, Segment, Source, Span
from atlas.ontology import load
from atlas.reason.shacl import validate

TEXT = "Line A supports the claim; dataset D was used by run R; the claim itself."
SOURCE = Source(id="s1", origin="s.txt", segments=(Segment(number=1, text=TEXT),))


def span(start: int, end: int) -> tuple[Span, ...]:
    return (Span.of(SOURCE, 1, start, end),)


def node(node_id: str, type_name: str, **fields: str) -> Node:
    return Node(id=node_id, type=type_name, fields=fields, spans=span(0, 6), schema_version="v")


def link(link_id: str, predicate: str, src: str, dst: str) -> Link:
    return Link(id=link_id, predicate=predicate, src=src, dst=dst, spans=span(7, 15),
                schema_version="v")


SCHEMA = load("science_core_rl", shapes=["science_core"])


def refused(nodes, links=()) -> set[str]:  # noqa: ANN001
    return validate(SCHEMA, nodes, links).refused()


def test_a_field_the_class_does_not_declare_is_refused() -> None:
    assert refused([node("p", "Proposition", expression="x", colour="red")]) == {"p"}


def test_a_subclass_node_is_not_refused_for_fields_its_superclass_lacks() -> None:
    """A closed shape targets its own class's nodes, not every instance of it."""
    assert refused([node("d", "Document", title="A paper", name="paper")]) == set()


def test_a_relation_whose_subject_is_not_recorded_as_its_domain_is_refused() -> None:
    nodes = [node("ds", "Dataset", name="D"), node("p", "Proposition", expression="x")]
    # The relation is what is wrong; the dataset may be exactly what it says it is.
    assert refused(nodes, [link("l", "supports", "ds", "p")]) == {"l"}


def test_a_node_of_a_subclass_satisfies_a_domain_check() -> None:
    nodes = [node("line", "SupportingLine"), node("p", "Proposition", expression="x")]
    assert refused(nodes, [link("l", "supports", "line", "p")]) == set()


def test_a_warning_is_reported_and_keeps_the_object() -> None:
    report = validate(SCHEMA, [node("line", "EvidenceLine", summary="a")])
    assert [one.severity for one in report.violations] == ["warning"]
    assert report.refused() == set()


def test_a_computation_depending_on_itself_through_a_chain_is_refused() -> None:
    nodes = [node(one, "Computation", name=one) for one in "ABC"]
    links = [link(f"{a}{b}", "directly_depends_on", a, b) for a, b in ("AB", "BC", "CA")]
    assert refused(nodes, links) == {"A", "B", "C"}
    assert refused(nodes, links[:2]) == set()


def test_a_statement_on_two_propositions_is_refused() -> None:
    nodes = [node("st", "Statement", text="S"), node("p1", "Proposition", expression="a"),
             node("p2", "Proposition", expression="b")]
    links = [link("a", "states", "st", "p1"), link("b", "states", "st", "p2")]
    assert refused(nodes, links) == {"st"}


def test_a_shape_is_named_by_a_valid_iri_whatever_its_class_is_called() -> None:
    from atlas.ontology import load_text
    from atlas.reason.shacl import generated

    schema = load_text("""
types:
  - name: Study result
    fields: [value]
    description: A class whose name has a space in it.
""")
    shapes = generated(schema, [node("n1", "Study result", value="0.94")])

    named = {str(shape) for shape in shapes.subjects() if "fields" in str(shape)}
    assert named == {"urn:atlas:shape:fields:Study%20result"}
    assert shapes.serialize(format="nt")
