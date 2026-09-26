"""SHACL: what a record must carry, checked in closed world, where OWL cannot check it.

OWL says what follows. It cannot say what must be there: under the open-world assumption a
node with no `observed_under` is not a node without conditions, it is a node whose
conditions nobody mentioned, and no OWL reasoner will ever complain about it. That is the
right reading for inference and the wrong one for a record that is about to be relied on,
so the two are kept apart. The ontology is reasoned over by the engines; the record is
validated by SHACL, against shapes (W3C, 2017), with pySHACL.

Two sets of shapes are applied.

**The shapes the ontology implies**, generated here: each class's fields and nothing else
(a closed shape -- what `Schema.validate_node` checks, stated as SHACL), every node on at
least one span (no provenance, no node), and each relation's domain and range as a
closed-world `sh:class` -- the subject of `supports` must already be an EvidenceLine, not
become one by inference.

**The shapes a configuration names**, hand-written under `ontologies/shapes/`: the rules
the ontology cannot state. A computation that depends on itself through a chain, a result
with no conditions recorded, a statement that states two propositions.

Validation runs with inference switched off (`inference="none"`) and the ontology given
only so that `sh:class` can walk `rdfs:subClassOf`. Reasoning is the engines' job, and a
validator that inferred as it validated would pass a node for being what it was only
inferred to be.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import quote

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection

from atlas.model import Link, Node, Schema
from atlas.model.owl import TOP
from atlas.ontology import abox
from atlas.ontology.rdf import to_graph as tbox_graph
from atlas.ontology.vocabulary import ATLAS, RDF, RDFS, SH, XSD

SEVERITIES = {str(SH.Violation): "violation", str(SH.Warning): "warning", str(SH.Info): "info"}


@dataclass(frozen=True)
class Violation:
    """One thing a record fails, with the node or link it is about."""

    focus: str
    target: str | None
    message: str
    severity: str
    path: str = ""
    shape: str = ""

    @property
    def refuses(self) -> bool:
        """Whether this finding stops the object being written; a warning does not."""
        return self.severity == "violation"


@dataclass(frozen=True)
class Report:
    conforms: bool
    violations: tuple[Violation, ...] = ()

    def refused(self) -> set[str]:
        """The ids of the nodes and links a violation, not a warning, was found on."""
        return {one.target for one in self.violations if one.refuses and one.target}


def generated(schema: Schema, nodes: Iterable[Node] = ()) -> Graph:
    """The shapes the ontology itself implies, in closed world.

    The field shapes are closed over a class's own fields and target the nodes asserted to
    be of exactly that class (`sh:targetNode`), not every instance of it: a `targetClass`
    shape would also target instances of every subclass, and a closed shape for Entity
    would then refuse a Document for having a title.
    """
    by_type: dict[str, list[str]] = {}
    for node in nodes:
        by_type.setdefault(node.type, []).append(node.id)
    g = Graph(bind_namespaces="core")
    g.bind("sh", SH)
    ignored = [RDF.type, ATLAS.evidence, ATLAS.schemaVersion,
               *(abox.property_iri(schema, one.name) for one in schema.predicates)]
    provenance = URIRef("urn:atlas:shape:provenance")
    g.add((provenance, RDF.type, SH.NodeShape))
    g.add((provenance, SH.targetClass, ATLAS.Node))
    _property(g, provenance, ATLAS.evidence, minimum=1,
              message="no provenance, no node: this node stands on no span")
    for type_def in schema.types:
        if type_def.defined:
            continue
        members = by_type.get(type_def.name, ())
        if not members:
            continue
        shape = _shape("fields", type_def.name)
        g.add((shape, RDF.type, SH.NodeShape))
        for member in members:
            g.add((shape, SH.targetNode, abox.node_iri(member)))
        allowed = list(ignored)
        for field in schema.declared_fields(type_def.name):
            path = abox.field_iri(schema, type_def.name, field.name)
            allowed.append(path)
            _property(g, shape, path, maximum=1,
                      message=f"{type_def.name}.{field.name} holds one value")
        # Closed only for the record's own fields: the relations it stands in and the
        # evidence it carries are ignored, and any other field is a field the ontology
        # does not declare for this class.
        g.add((shape, SH.closed, Literal(True)))
        head = BNode()
        Collection(g, head, list(dict.fromkeys(allowed)))
        g.add((shape, SH.ignoredProperties, head))
    for predicate in schema.predicates:
        prop = abox.property_iri(schema, predicate.name)
        for end, target in (("domain", SH.targetSubjectsOf), ("range", SH.targetObjectsOf)):
            expected = getattr(predicate, end)
            if not expected or expected == TOP or schema.find_type(expected) is None:
                continue
            shape = _shape(end, predicate.name)
            g.add((shape, RDF.type, SH.NodeShape))
            g.add((shape, target, prop))
            g.add((shape, SH["class"], abox.class_iri(schema, expected)))
            g.add((shape, SH.message, Literal(
                f"the {'subject' if end == 'domain' else 'object'} of {predicate.name} "
                f"is not recorded as a {expected}")))
    return g


def _shape(kind: str, name: str) -> URIRef:
    """The IRI a generated shape is named by, valid whatever the class or relation is called.

    A vocabulary names its terms in its own language and its own spelling -- with a space,
    in Cyrillic -- and a name pasted into an IRI as it is makes one no serialiser will
    write. The name is percent-encoded, so the shape is still found by it.
    """
    return URIRef(f"urn:atlas:shape:{kind}:{quote(name, safe='')}")


def _property(g: Graph, shape: URIRef, path: URIRef, *, minimum: int | None = None,
              maximum: int | None = None, message: str = "") -> None:
    node = BNode()
    g.add((shape, SH.property, node))
    g.add((node, SH.path, path))
    if minimum is not None:
        g.add((node, SH.minCount, Literal(minimum, datatype=XSD.integer)))
    if maximum is not None:
        g.add((node, SH.maxCount, Literal(maximum, datatype=XSD.integer)))
    if message:
        g.add((node, SH.message, Literal(message)))


def ontology_graph(schema: Schema) -> Graph:
    """The ontology as RDF, with the reasoner's hierarchy written in as told subclasses.

    `sh:class` walks `rdfs:subClassOf` in the ontology graph and nothing more. Writing the
    classified hierarchy in is what lets a node of a class the ontology *implies* is a
    subclass pass a range check, without the validator doing any reasoning of its own.
    """
    g = tbox_graph(schema)
    for name, supers in schema.hierarchy.items():
        for sup in supers:
            g.add((abox.class_iri(schema, name), RDFS.subClassOf, abox.class_iri(schema, sup)))
    return g


def validate(
    schema: Schema,
    nodes: Iterable[Node],
    links: Iterable[Link] = (),
    *,
    shapes: str | None = None,
    generate: bool = True,
) -> Report:
    """Validate a record against the ontology's shapes and the configuration's.

    `shapes` defaults to the ones the schema was loaded with -- the shapes a configuration
    named are part of its schema, and hashed into its version, for exactly this reason.
    """
    from pyshacl import validate as run

    nodes, links = list(nodes), list(links)
    data = abox.to_graph(schema, nodes, links)
    shape_graph = generated(schema, nodes) if generate else Graph()
    written = schema.shapes if shapes is None else shapes
    if written.strip():
        shape_graph.parse(data=written, format="turtle")
    if len(shape_graph) == 0:
        return Report(conforms=True)
    conforms, results, _ = run(
        data, shacl_graph=shape_graph, ont_graph=ontology_graph(schema),
        inference="none", advanced=True, allow_warnings=True, meta_shacl=False,
    )
    return Report(conforms=bool(conforms), violations=_violations(results, data, shape_graph))


def _violations(results: Graph, data: Graph, shapes: Graph) -> tuple[Violation, ...]:
    found: list[Violation] = []
    for result in results.subjects(RDF.type, SH.ValidationResult):
        focus = results.value(result, SH.focusNode)
        path = results.value(result, SH.resultPath)
        message = results.value(result, SH.resultMessage)
        severity = results.value(result, SH.resultSeverity)
        shape = results.value(result, SH.sourceShape)
        for target in _targets(focus, shape, data, shapes):
            found.append(Violation(
                focus=str(focus), target=target, message=str(message or ""),
                severity=SEVERITIES.get(str(severity), "violation"),
                path=str(path) if isinstance(path, URIRef) else "",
                shape=str(shape) if isinstance(shape, URIRef) else "",
            ))
    return tuple(sorted(found, key=lambda one: (one.target or "", one.message)))


def _targets(focus: object, shape: object, data: Graph, shapes: Graph) -> list[str | None]:
    """What a finding refuses: the relation, for a domain or range check; else the focus.

    A domain check fails on the node at one end of a relation, but what is wrong is the
    relation -- the node may be exactly what it says it is. So a finding from a shape that
    targets the subjects or objects of a relation refuses each such relation touching the
    node, and leaves the node alone.
    """
    for end, target in ((RDF.subject, SH.targetSubjectsOf), (RDF.object, SH.targetObjectsOf)):
        prop = shapes.value(shape, target) if isinstance(shape, URIRef) else None
        if prop is not None and isinstance(focus, URIRef):
            links = [abox.identity(str(one)) for one in data.subjects(end, focus)
                     if (one, RDF.predicate, prop) in data]
            if links:
                return list(links)
    return [_target(focus, data)]


def _target(focus: object, data: Graph) -> str | None:
    """The node or link a finding is about: its own id, or the object whose span it is."""
    if not isinstance(focus, URIRef):
        return None
    own = abox.identity(str(focus))
    if own is not None:
        return own
    owner = next(iter(data.subjects(ATLAS.evidence, focus)), None)
    return abox.identity(str(owner)) if owner is not None else None


__all__ = ["Report", "Violation", "generated", "ontology_graph", "validate"]
