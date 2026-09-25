"""Nodes and links written as RDF, the way an ontology engine and a SHACL validator read them.

The store keeps nodes and links as the metamodel's own objects; this is their RDF face. A
node is an individual whose `rdf:type` is its class's IRI and whose fields are datatype
property values. A link is a triple between two such individuals, and also a reified
statement (`atlas:Link`) so it can carry its own evidence. Every span is a W3C Web
Annotation selector pair -- a text position and the exact quote at it -- on its source.

Two properties of this mapping are worth knowing:

* **A field the class does not declare is still written**, under an IRI that names no
  property of the ontology. That is how a closed SHACL shape sees it and refuses it, which
  is the whole point of validating in closed world;
* **A derived link is written with `atlas:derivedBy`**, naming the rule. An RDF consumer
  that reads the graph can tell an inference from a claim, which is the one thing this
  library promises about inferences.

Identifiers are URNs (`urn:atlas:node:<id>`), not web IRIs: a node's identity is its
content hash, and a namespace nobody controls would make it look like something that
could be dereferenced.
"""

from __future__ import annotations

from collections.abc import Iterable

from rdflib import BNode, Graph, Literal, URIRef

from atlas.model import Link, Node, Schema, Span
from atlas.ontology.vocabulary import ATLAS, LOCAL, OA, RDF, XSD, local_field

NODE = "urn:atlas:node:"
LINK = "urn:atlas:link:"
SOURCE = "urn:atlas:source:"
SPAN = "urn:atlas:span:"


def node_iri(node_id: str) -> URIRef:
    return URIRef(f"{NODE}{node_id}")


def link_iri(link_id: str) -> URIRef:
    return URIRef(f"{LINK}{link_id}")


def identity(iri: str) -> str | None:
    """The node or link id an ABox IRI stands for, or None for anything else."""
    for prefix in (NODE, LINK):
        if iri.startswith(prefix):
            return iri[len(prefix):]
    return None


def class_iri(schema: Schema, name: str) -> URIRef:
    found = schema.find_type(name)
    return URIRef(found.iri) if found is not None and found.iri else URIRef(f"{LOCAL}{name}")


def property_iri(schema: Schema, name: str) -> URIRef:
    found = schema.find_predicate(name)
    return URIRef(found.iri) if found is not None and found.iri else URIRef(f"{LOCAL}{name}")


def field_iri(schema: Schema, type_name: str, field: str) -> URIRef:
    declared = next((one for one in schema.declared_fields(type_name) if one.name == field), None)
    if declared is not None and declared.iri:
        return URIRef(declared.iri)
    return URIRef(local_field(field, declared.datatype if declared is not None else "string"))


def to_graph(
    schema: Schema,
    nodes: Iterable[Node],
    links: Iterable[Link] = (),
    *,
    typings: Iterable[tuple[str, str]] = (),
    derived: Iterable[Link] = (),
) -> Graph:
    """The nodes and links, and any inferred typings and derived links, as one RDF graph."""
    g = Graph(bind_namespaces="core")
    g.bind("atlas", ATLAS)
    g.bind("oa", OA)
    for node in nodes:
        subject = node_iri(node.id)
        g.add((subject, RDF.type, ATLAS.Node))
        g.add((subject, RDF.type, class_iri(schema, node.type)))
        g.add((subject, ATLAS.schemaVersion, Literal(node.schema_version)))
        for name, value in node.fields.items():
            g.add((subject, field_iri(schema, node.type, name), Literal(value)))
        for span in node.spans:
            g.add((subject, ATLAS.evidence, _span(g, span)))
    for node_id, type_name in typings:
        g.add((node_iri(node_id), RDF.type, class_iri(schema, type_name)))
    for link in links:
        _link(g, schema, link)
    for link in derived:
        subject = _link(g, schema, link)
        g.add((subject, ATLAS.derivedBy, Literal(link.fields.get("derived", ""))))
    return g


def _link(g: Graph, schema: Schema, link: Link) -> URIRef:
    predicate = property_iri(schema, link.predicate)
    g.add((node_iri(link.src), predicate, node_iri(link.dst)))
    subject = link_iri(link.id)
    g.add((subject, RDF.type, ATLAS.Link))
    g.add((subject, RDF.subject, node_iri(link.src)))
    g.add((subject, RDF.predicate, predicate))
    g.add((subject, RDF.object, node_iri(link.dst)))
    for span in link.spans:
        g.add((subject, ATLAS.evidence, _span(g, span)))
    return subject


def _span(g: Graph, span: Span) -> URIRef:
    subject = URIRef(f"{SPAN}{span.source_id}:{span.segment}:{span.start}:{span.end}")
    g.add((subject, RDF.type, ATLAS.Span))
    g.add((subject, OA.hasSource, URIRef(f"{SOURCE}{span.source_id}")))
    g.add((subject, ATLAS.segment, Literal(span.segment, datatype=XSD.integer)))
    position, quote = BNode(), BNode()
    g.add((subject, OA.hasSelector, position))
    g.add((position, RDF.type, OA.TextPositionSelector))
    g.add((position, OA.start, Literal(span.start, datatype=XSD.nonNegativeInteger)))
    g.add((position, OA.end, Literal(span.end, datatype=XSD.nonNegativeInteger)))
    g.add((subject, OA.hasSelector, quote))
    g.add((quote, RDF.type, OA.TextQuoteSelector))
    g.add((quote, OA.exact, Literal(span.text)))
    return subject


__all__ = ["class_iri", "field_iri", "identity", "link_iri", "node_iri", "property_iri",
           "to_graph"]
