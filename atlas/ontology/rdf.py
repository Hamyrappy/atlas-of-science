"""An OWL 2 ontology in RDF, read into axioms and a vocabulary, and written back out.

This is the OWL 2 mapping to RDF graphs (W3C, 2012) read in the reverse direction: an
`rdfs:subClassOf` between two class expressions is a `SubClassOf` axiom, a blank node with
`owl:someValuesFrom` is an existential restriction, an `owl:AllDisjointClasses` with its
members is a `DisjointClasses` axiom, and so on through the table. What comes out is the
structural model of `atlas.model.owl`, which is what every engine reasons with, together
with the projection a configuration reads: one `TypeDef` per named class, one
`PredicateDef` per object property, one `FieldDef` per datatype property a class lists.

**Names are resolved once, over the whole merge.** Several files loaded together are one
RDF graph before anything is named, so a class declared with `atlas:name "Process"` in one
file is `Process` in every axiom of every other file that mentions its IRI. A name two
different IRIs claim is refused: a configuration that says `Method` must mean one thing.

**What is not modelled is named, not dropped.** Data ranges, datatype restrictions and
nominals parse without error and come back in `unread`, by the triple that states them,
so a reader of the schema knows the ontology said more than the engines heard.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.term import Node as Term

from atlas.model.owl import (
    BOTTOM,
    TOP,
    And,
    Axiom,
    Cardinality,
    ClassExpression,
    DisjointClasses,
    DisjointProperties,
    Domain,
    EquivalentClasses,
    EquivalentProperties,
    HasCharacteristic,
    HasValue,
    InverseProperties,
    Named,
    Not,
    Only,
    Or,
    Property,
    Range,
    Some,
    SubClassOf,
    SubPropertyOf,
)
from atlas.model.schema import FieldDef, PredicateDef, Schema, TypeDef
from atlas.ontology.vocabulary import (
    ATLAS,
    DATATYPES,
    LOCAL,
    MATCHES,
    OWL,
    RDF,
    RDFS,
    SKOS,
    XSD,
    local_field,
)

CHARACTERISTIC_TYPES = {
    OWL.TransitiveProperty: "transitive", OWL.SymmetricProperty: "symmetric",
    OWL.AsymmetricProperty: "asymmetric", OWL.ReflexiveProperty: "reflexive",
    OWL.IrreflexiveProperty: "irreflexive", OWL.FunctionalProperty: "functional",
    OWL.InverseFunctionalProperty: "inverse-functional",
}
OBJECT_PROPERTY_TYPES = {OWL.ObjectProperty, *CHARACTERISTIC_TYPES} - {OWL.FunctionalProperty}


class Unsupported(ValueError):
    """A construct the structural model does not have, named by what it is."""


@dataclass
class Projection:
    """What one merged graph says: the vocabulary, the axioms, and what was not read."""

    iri: str = ""
    types: list[TypeDef] = field(default_factory=list)
    predicates: list[PredicateDef] = field(default_factory=list)
    axioms: list[Axiom] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)


class Reader:
    """One merged graph, with every IRI it uses given its one name."""

    def __init__(self, graph: Graph, order: dict[str, float] | None = None) -> None:
        self.g = graph
        self.order = order or {}
        self.datatype_properties = {
            s for s in graph.subjects(RDF.type, OWL.DatatypeProperty) if isinstance(s, URIRef)
        }
        self.object_properties = {
            s for kind in OBJECT_PROPERTY_TYPES for s in graph.subjects(RDF.type, kind)
            if isinstance(s, URIRef)
        }
        self.object_properties |= {
            s for s in graph.subjects(RDF.type, OWL.FunctionalProperty)
            if isinstance(s, URIRef) and s not in self.datatype_properties
        }
        for predicate in (OWL.inverseOf, OWL.propertyDisjointWith, OWL.equivalentProperty):
            for s, o in graph.subject_objects(predicate):
                for one in (s, o):
                    if isinstance(one, URIRef) and one not in self.datatype_properties:
                        self.object_properties.add(one)
        for s, o in graph.subject_objects(RDFS.subPropertyOf):
            if s in self.object_properties or o in self.object_properties:
                for one in (s, o):
                    if isinstance(one, URIRef):
                        self.object_properties.add(one)
        for s in graph.subjects(OWL.propertyChainAxiom, None):
            if isinstance(s, URIRef):
                self.object_properties.add(s)
        for restriction in graph.subjects(RDF.type, OWL.Restriction):
            prop = graph.value(restriction, OWL.onProperty)
            if isinstance(prop, URIRef) and prop not in self.datatype_properties:
                self.object_properties.add(prop)
        self.classes = {
            s for s in graph.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)
        } - {OWL.Thing, OWL.Nothing}
        # Only a declared class is part of the vocabulary. An axiom may mention a class
        # nobody declared -- that is legal OWL, and it is named like any other -- but a
        # configuration is offered what an ontology declares, and a legacy pack's parent
        # or domain that names nothing stays a finding for the formal gate to report.
        self.declared_classes = set(self.classes)
        self.declared_properties = set(self.object_properties) - {
            s for s in self.object_properties if (s, RDF.type, OWL.ObjectProperty) not in graph
            and not any((s, RDF.type, kind) in graph for kind in CHARACTERISTIC_TYPES)
        }
        self.unread: list[str] = []
        self.class_names = self._names(self.classes, "class")
        self.property_names = self._names(self.object_properties, "relation")
        # Two datatype properties with one name are one field: a node's fields are keyed by
        # name, so they could only ever fill the same slot, and refusing them would refuse
        # a legacy pack loaded beside an ontology that declares the same common word.
        self.field_names = {iri: self._name(iri) for iri in self.datatype_properties}

    # -- names ------------------------------------------------------------------------------

    def _names(self, iris: Iterable[URIRef], what: str) -> dict[URIRef, str]:
        named: dict[URIRef, str] = {}
        taken: dict[str, URIRef] = {}
        for iri in sorted(iris, key=str):
            name = self._name(iri)
            if name in taken and taken[name] != iri:
                raise ValueError(f"duplicate name {name!r}: the {what}s {taken[name]} and "
                                 f"{iri} both claim it")
            taken[name] = iri
            named[iri] = name
        return named

    def _name(self, iri: URIRef) -> str:
        given = self.g.value(iri, ATLAS.name)
        if given is not None:
            return str(given)
        return local_part(str(iri))

    def class_name(self, iri: URIRef) -> str:
        if iri == OWL.Thing:
            return TOP
        if iri == OWL.Nothing:
            return BOTTOM
        if iri not in self.class_names:
            self.classes.add(iri)
            name = self._name(iri)
            clash = next((one for one, n in self.class_names.items() if n == name), None)
            if clash is not None:
                raise ValueError(f"duplicate name {name!r}: the classes {clash} and {iri} "
                                 "both claim it")
            self.class_names[iri] = name
        return self.class_names[iri]

    def property_name(self, iri: URIRef) -> str:
        if iri not in self.property_names:
            self.object_properties.add(iri)
            self.property_names[iri] = self._name(iri)
        return self.property_names[iri]

    # -- class and property expressions -----------------------------------------------------

    def property(self, node: Term) -> Property:
        if isinstance(node, URIRef):
            if node in self.datatype_properties:
                raise Unsupported(f"a restriction on the datatype property {node}")
            return Property(name=self.property_name(node))
        inner = self.g.value(node, OWL.inverseOf)
        if isinstance(inner, URIRef):
            return Property(name=self.property_name(inner), inverse=True)
        raise Unsupported(f"an object property expression {node} this library cannot read")

    def expression(self, node: Term) -> ClassExpression:
        g = self.g
        if isinstance(node, URIRef):
            return Named(name=self.class_name(node))
        if isinstance(node, Literal):
            raise Unsupported(f"a literal {node!r} where a class was expected")
        for predicate, build in ((OWL.intersectionOf, And), (OWL.unionOf, Or)):
            members = g.value(node, predicate)
            if members is not None:
                return build(operands=tuple(self.expression(one)
                                            for one in Collection(g, members)))
        complement = g.value(node, OWL.complementOf)
        if complement is not None:
            return Not(operand=self.expression(complement))
        if g.value(node, OWL.oneOf) is not None:
            raise Unsupported("an enumeration of individuals (owl:oneOf)")
        prop_node = g.value(node, OWL.onProperty)
        if prop_node is None:
            if g.value(node, OWL.onProperties) is not None:
                raise Unsupported("an n-ary data restriction")
            raise Unsupported(f"a class expression {node} with nothing this library reads")
        prop = self.property(prop_node)
        for predicate, build in ((OWL.someValuesFrom, Some), (OWL.allValuesFrom, Only)):
            filler = g.value(node, predicate)
            if filler is not None:
                if self._is_datatype(filler):
                    raise Unsupported(f"a data range {filler}")
                return build(property=prop, filler=self.expression(filler))
        value = g.value(node, OWL.hasValue)
        if value is not None:
            if isinstance(value, Literal):
                raise Unsupported(f"a data value restriction {value!r}")
            return HasValue(property=prop, individual=local_part(str(value)))
        for predicate, bound, qualified in (
            (OWL.minQualifiedCardinality, "min", True), (OWL.maxQualifiedCardinality, "max", True),
            (OWL.qualifiedCardinality, "exactly", True), (OWL.minCardinality, "min", False),
            (OWL.maxCardinality, "max", False), (OWL.cardinality, "exactly", False),
        ):
            count = g.value(node, predicate)
            if count is not None:
                on_class = g.value(node, OWL.onClass) if qualified else None
                filler = self.expression(on_class) if on_class is not None else Named(name=TOP)
                return Cardinality(bound=bound, count=int(count), property=prop, filler=filler)
        raise Unsupported(f"a restriction on {prop.text()} this library cannot read")

    def _is_datatype(self, node: Term) -> bool:
        return (isinstance(node, URIRef) and str(node).startswith(str(XSD))) or (
            self.g.value(node, RDF.type) == RDFS.Datatype)

    # -- axioms -----------------------------------------------------------------------------

    def axioms(self) -> list[Axiom]:
        g = self.g
        found: list[Axiom] = []

        def take(build, triple: str) -> None:  # noqa: ANN001 -- a thunk
            try:
                result = build()
            except Unsupported as unsupported:
                self.unread.append(f"{triple}: {unsupported}")
                return
            if isinstance(result, list):
                found.extend(result)
            elif result is not None:
                found.append(result)

        for s, o in g.subject_objects(RDFS.subClassOf):
            take(lambda s=s, o=o: SubClassOf(sub=self.expression(s), sup=self.expression(o)),
                 f"{_show(s)} rdfs:subClassOf {_show(o)}")
        for s, o in g.subject_objects(OWL.equivalentClass):
            take(lambda s=s, o=o: EquivalentClasses(
                classes=(self.expression(s), self.expression(o))),
                f"{_show(s)} owl:equivalentClass {_show(o)}")
        for s, o in g.subject_objects(OWL.disjointWith):
            take(lambda s=s, o=o: DisjointClasses(
                classes=(self.expression(s), self.expression(o))),
                f"{_show(s)} owl:disjointWith {_show(o)}")
        for node in g.subjects(RDF.type, OWL.AllDisjointClasses):
            members = g.value(node, OWL.members)
            take(lambda members=members: DisjointClasses(
                classes=tuple(self.expression(one) for one in Collection(g, members))),
                "owl:AllDisjointClasses")
        for s, o in g.subject_objects(OWL.disjointUnionOf):
            def union(s=s, o=o) -> list[Axiom]:
                parts = tuple(self.expression(one) for one in Collection(g, o))
                return [EquivalentClasses(classes=(self.expression(s), Or(operands=parts))),
                        DisjointClasses(classes=parts)]
            take(union, f"{_show(s)} owl:disjointUnionOf")
        for s, o in g.subject_objects(RDFS.subPropertyOf):
            if s in self.datatype_properties or o in self.datatype_properties:
                continue
            if not (s in self.object_properties or isinstance(s, BNode)):
                continue
            take(lambda s=s, o=o: SubPropertyOf(sub=(self.property(s),), sup=self.property(o)),
                 f"{_show(s)} rdfs:subPropertyOf {_show(o)}")
        for s, o in g.subject_objects(OWL.propertyChainAxiom):
            take(lambda s=s, o=o: SubPropertyOf(
                sub=tuple(self.property(one) for one in Collection(g, o)),
                sup=self.property(s)), f"{_show(s)} owl:propertyChainAxiom")
        for s, o in g.subject_objects(OWL.equivalentProperty):
            if s in self.datatype_properties:
                continue
            take(lambda s=s, o=o: EquivalentProperties(
                properties=(self.property(s), self.property(o))),
                f"{_show(s)} owl:equivalentProperty {_show(o)}")
        for s, o in g.subject_objects(OWL.propertyDisjointWith):
            take(lambda s=s, o=o: DisjointProperties(
                properties=(self.property(s), self.property(o))),
                f"{_show(s)} owl:propertyDisjointWith {_show(o)}")
        for node in g.subjects(RDF.type, OWL.AllDisjointProperties):
            members = g.value(node, OWL.members)
            take(lambda members=members: DisjointProperties(
                properties=tuple(self.property(one) for one in Collection(g, members))),
                "owl:AllDisjointProperties")
        for s, o in g.subject_objects(OWL.inverseOf):
            if isinstance(s, URIRef) and isinstance(o, URIRef):
                take(lambda s=s, o=o: InverseProperties(
                    first=self.property_name(s), second=self.property_name(o)),
                    f"{_show(s)} owl:inverseOf {_show(o)}")
        for p, c in g.subject_objects(RDFS.domain):
            if p in self.object_properties:
                take(lambda p=p, c=c: Domain(property=self.property_name(p),
                                             domain=self.expression(c)),
                     f"{_show(p)} rdfs:domain {_show(c)}")
        for p, c in g.subject_objects(RDFS.range):
            if p in self.object_properties:
                take(lambda p=p, c=c: Range(property=self.property_name(p),
                                            range=self.expression(c)),
                     f"{_show(p)} rdfs:range {_show(c)}")
        for kind, characteristic in CHARACTERISTIC_TYPES.items():
            for p in g.subjects(RDF.type, kind):
                if p in self.object_properties and isinstance(p, URIRef):
                    found.append(HasCharacteristic(property=self.property_name(p),
                                                   characteristic=characteristic))
        return _unique(found)

    # -- the vocabulary ---------------------------------------------------------------------

    def projection(self) -> Projection:
        axioms = self.axioms()
        g = self.g
        ontology = next((s for s in g.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)),
                        None)
        told: dict[str, list[str]] = {}
        disjoint: dict[str, list[str]] = {}
        domains: dict[str, str] = {}
        ranges: dict[str, str] = {}
        characteristics: dict[str, list[str]] = {}
        inverse: dict[str, str] = {}
        parents: dict[str, list[str]] = {}
        for axiom in axioms:
            if isinstance(axiom, SubClassOf) and isinstance(axiom.sub, Named) and isinstance(
                axiom.sup, Named
            ):
                told.setdefault(axiom.sub.name, []).append(axiom.sup.name)
            elif isinstance(axiom, DisjointClasses):
                names = [one.name for one in axiom.classes if isinstance(one, Named)]
                for name in names:
                    disjoint.setdefault(name, []).extend(n for n in names if n != name)
            elif isinstance(axiom, Domain) and isinstance(axiom.domain, Named):
                domains.setdefault(axiom.property, axiom.domain.name)
            elif isinstance(axiom, Range) and isinstance(axiom.range, Named):
                ranges.setdefault(axiom.property, axiom.range.name)
            elif isinstance(axiom, HasCharacteristic):
                characteristics.setdefault(axiom.property, []).append(axiom.characteristic)
            elif isinstance(axiom, InverseProperties):
                inverse.setdefault(axiom.first, axiom.second)
            elif isinstance(axiom, SubPropertyOf) and not axiom.chain and not (
                axiom.sub[0].inverse or axiom.sup.inverse
            ):
                parents.setdefault(axiom.sub[0].name, []).append(axiom.sup.name)
        # A word a legacy pack wrote as a characteristic that OWL does not have. It is no
        # axiom, but it is what the pack said, and the formal gate refuses it by name.
        for prop, word in g.subject_objects(ATLAS.characteristic):
            if isinstance(prop, URIRef) and prop in self.property_names:
                characteristics.setdefault(self.property_names[prop], []).append(str(word))
        types = [
            TypeDef(
                name=name,
                iri=_identity(iri),
                parent=sorted(told.get(name, []))[0] if told.get(name) else None,
                fields=self._fields(iri),
                label_field=self._label_field(iri),
                mappings=self._mappings(iri),
                disjoint_with=tuple(dict.fromkeys(disjoint.get(name, ()))),
                description=self._description(iri),
                defined=_true(g.value(iri, ATLAS.inferred)),
            )
            for iri, name in self._ordered(self.class_names)
            if iri in self.declared_classes
        ]
        predicates = [
            PredicateDef(
                name=name,
                iri=_identity(iri),
                domain=domains.get(name, TOP),
                range=ranges.get(name, TOP),
                mappings=self._mappings(iri),
                characteristics=tuple(dict.fromkeys(characteristics.get(name, ()))),
                inverse_of=inverse.get(name),
                parents=tuple(dict.fromkeys(parents.get(name, ()))),
                description=self._description(iri),
            )
            for iri, name in self._ordered(self.property_names)
            if iri in self.declared_properties
        ]
        return Projection(
            iri=str(ontology) if ontology is not None else "",
            types=types,
            predicates=predicates,
            axioms=axioms,
            unread=list(self.unread),
            imports=[str(one) for one in g.objects(None, OWL.imports)],
            profiles=[str(one) for one in g.objects(None, ATLAS.profile)],
        )

    def _ordered(self, named: dict[URIRef, str]) -> list[tuple[URIRef, str]]:
        return sorted(named.items(), key=lambda item: (self.order.get(str(item[0]), 1e12),
                                                       item[1]))

    def _fields(self, iri: URIRef) -> tuple[FieldDef, ...]:
        listed = self.g.value(iri, ATLAS.fields)
        if listed is None:
            return ()
        fields = []
        for prop in Collection(self.g, listed):
            if not isinstance(prop, URIRef):
                continue
            datatype = self.g.value(prop, ATLAS.datatype)
            if datatype is None:
                rng = self.g.value(prop, RDFS.range)
                datatype = DATATYPES.get(str(rng), local_part(str(rng))) if rng else "string"
            fields.append(FieldDef(name=self.field_names.get(prop, self._name(prop)),
                                   datatype=str(datatype), iri=_identity(prop)))
        return tuple(fields)

    def _label_field(self, iri: URIRef) -> str | None:
        prop = self.g.value(iri, ATLAS.labelField)
        if prop is None:
            return None
        return self.field_names.get(prop, self._name(prop)) if isinstance(prop, URIRef) else str(
            prop)

    def _mappings(self, iri: URIRef) -> tuple[str, ...]:
        found: list[str] = []
        listed = self.g.value(iri, ATLAS.mappings)
        if listed is not None:
            found += [str(one) for one in Collection(self.g, listed)]
        for predicate in MATCHES:
            found += sorted(self._compact(one) for one in self.g.objects(iri, predicate))
        return tuple(dict.fromkeys(found))

    def _description(self, iri: URIRef) -> str:
        for predicate in (SKOS.definition, RDFS.comment):
            value = self.g.value(iri, predicate)
            if value is not None:
                return " ".join(str(value).split())
        return ""

    def _compact(self, term: Term) -> str:
        if not isinstance(term, URIRef):
            return str(term)
        try:
            prefix, namespace, name = self.g.namespace_manager.compute_qname(str(term),
                                                                            generate=False)
        except (KeyError, ValueError):
            return str(term)
        return f"{prefix}:{name}" if prefix else str(term)


def local_part(iri: str) -> str:
    """The last segment of an IRI, which is what a term is called when it names nothing."""
    if iri.startswith(LOCAL):
        return iri[len(LOCAL):].rsplit(":", 1)[-1]
    for separator in ("#", "/", ":"):
        if separator in iri:
            tail = iri.rsplit(separator, 1)[-1]
            if tail:
                return tail
    return iri


def declaration_order(text: str, graph: Graph, offset: float) -> dict[str, float]:
    """Where each term is first declared in a Turtle file, so a vocabulary reads in file order.

    RDF has no order and a graph remembers none, but a person who wrote `Entity` before
    `Process` meant it that way, and a prompt that listed the types alphabetically would
    be listing them in an order nobody chose. The position of the first line that starts
    with the term's prefixed name or IRI is what is read.
    """
    found: dict[str, float] = {}
    manager = graph.namespace_manager
    for subject in set(graph.subjects()):
        if not isinstance(subject, URIRef):
            continue
        names = [f"<{subject}>"]
        try:
            prefix, _, name = manager.compute_qname(str(subject), generate=False)
            names.insert(0, f"{prefix}:{name}")
        except (KeyError, ValueError):
            pass
        positions = [match.start() for one in names
                     for match in re.finditer(rf"(?m)^{re.escape(one)}(?=[\s;])", text)]
        if positions:
            found[str(subject)] = offset + min(positions) / max(len(text), 1)
    return found


def _true(value: Term | None) -> bool:
    return value is not None and str(value).lower() in ("true", "1")


def _identity(iri: URIRef) -> str | None:
    return None if str(iri).startswith(LOCAL) else str(iri)


def _show(term: Term) -> str:
    return f"<{term}>" if isinstance(term, URIRef) else "_:"


def _unique(axioms: list[Axiom]) -> list[Axiom]:
    seen: set = set()
    kept: list[Axiom] = []
    for axiom in axioms:
        if axiom not in seen:
            seen.add(axiom)
            kept.append(axiom)
    return kept


# ---- writing ------------------------------------------------------------------------------


def to_graph(schema: Schema) -> Graph:
    """A schema as an OWL 2 ontology in RDF: its vocabulary, its annotations and its axioms."""
    g = Graph()
    for prefix, namespace in schema.prefixes.items():
        g.bind(prefix, namespace)
    g.bind("owl", OWL)
    g.bind("atlas", ATLAS)
    g.bind("skos", SKOS)
    ontology = URIRef(schema.iri) if schema.iri else BNode()
    g.add((ontology, RDF.type, OWL.Ontology))
    if schema.profile:
        g.add((ontology, ATLAS.profile, Literal(schema.profile)))
    classes = {t.name: URIRef(t.iri or f"{LOCAL}{t.name}") for t in schema.types}
    properties = {p.name: URIRef(p.iri or f"{LOCAL}{p.name}") for p in schema.predicates}
    fields: dict[str, URIRef] = {}
    for type_def in schema.types:
        subject = classes[type_def.name]
        g.add((subject, RDF.type, OWL.Class))
        g.add((subject, ATLAS.name, Literal(type_def.name)))
        if type_def.description:
            g.add((subject, SKOS.definition, Literal(type_def.description)))
        listed = []
        for one in type_def.fields:
            prop = URIRef(one.iri or local_field(one.name, one.datatype))
            fields.setdefault(one.name, prop)
            g.add((prop, RDF.type, OWL.DatatypeProperty))
            g.add((prop, ATLAS.name, Literal(one.name)))
            g.add((prop, ATLAS.datatype, Literal(one.datatype)))
            listed.append(prop)
        if listed:
            head = BNode()
            Collection(g, head, listed)
            g.add((subject, ATLAS.fields, head))
        if type_def.label_field and type_def.label_field in fields:
            g.add((subject, ATLAS.labelField, fields[type_def.label_field]))
        if type_def.mappings:
            head = BNode()
            Collection(g, head, [Literal(one) for one in type_def.mappings])
            g.add((subject, ATLAS.mappings, head))
    for predicate in schema.predicates:
        subject = properties[predicate.name]
        g.add((subject, RDF.type, OWL.ObjectProperty))
        g.add((subject, ATLAS.name, Literal(predicate.name)))
        if predicate.description:
            g.add((subject, SKOS.definition, Literal(predicate.description)))
        if predicate.mappings:
            head = BNode()
            Collection(g, head, [Literal(one) for one in predicate.mappings])
            g.add((subject, ATLAS.mappings, head))
    writer = _Writer(g, classes, properties)
    for axiom in schema.every_axiom():
        writer.axiom(axiom)
    return g


def to_turtle(schema: Schema) -> str:
    return to_graph(schema).serialize(format="turtle")


class _Writer:
    def __init__(self, g: Graph, classes: dict[str, URIRef],
                 properties: dict[str, URIRef]) -> None:
        self.g, self.classes, self.properties = g, classes, properties

    def iri(self, name: str) -> URIRef:
        if name == TOP:
            return OWL.Thing
        if name == BOTTOM:
            return OWL.Nothing
        return self.classes.get(name) or URIRef(f"{LOCAL}{name}")

    def prop(self, prop: Property) -> Term:
        iri = self.properties.get(prop.name) or URIRef(f"{LOCAL}{prop.name}")
        if not prop.inverse:
            return iri
        node = BNode()
        self.g.add((node, OWL.inverseOf, iri))
        return node

    def expression(self, expression: ClassExpression) -> Term:
        g = self.g
        if isinstance(expression, Named):
            return self.iri(expression.name)
        node = BNode()
        if isinstance(expression, And | Or):
            head = BNode()
            Collection(g, head, [self.expression(one) for one in expression.operands])
            g.add((node, RDF.type, OWL.Class))
            g.add((node, OWL.intersectionOf if isinstance(expression, And) else OWL.unionOf, head))
            return node
        if isinstance(expression, Not):
            g.add((node, RDF.type, OWL.Class))
            g.add((node, OWL.complementOf, self.expression(expression.operand)))
            return node
        g.add((node, RDF.type, OWL.Restriction))
        g.add((node, OWL.onProperty, self.prop(expression.property)))
        if isinstance(expression, Some):
            g.add((node, OWL.someValuesFrom, self.expression(expression.filler)))
        elif isinstance(expression, Only):
            g.add((node, OWL.allValuesFrom, self.expression(expression.filler)))
        elif isinstance(expression, HasValue):
            g.add((node, OWL.hasValue, URIRef(f"{LOCAL}individual:{expression.individual}")))
        elif isinstance(expression, Cardinality):
            predicate = {"min": OWL.minQualifiedCardinality, "max": OWL.maxQualifiedCardinality,
                         "exactly": OWL.qualifiedCardinality}[expression.bound]
            g.add((node, predicate, Literal(expression.count)))
            g.add((node, OWL.onClass, self.expression(expression.filler)))
        return node

    def axiom(self, axiom: Axiom) -> None:
        g = self.g
        if isinstance(axiom, SubClassOf):
            g.add((self.expression(axiom.sub), RDFS.subClassOf, self.expression(axiom.sup)))
        elif isinstance(axiom, EquivalentClasses):
            first = self.expression(axiom.classes[0])
            for other in axiom.classes[1:]:
                g.add((first, OWL.equivalentClass, self.expression(other)))
        elif isinstance(axiom, DisjointClasses):
            if len(axiom.classes) == 2:
                g.add((self.expression(axiom.classes[0]), OWL.disjointWith,
                       self.expression(axiom.classes[1])))
            else:
                node, head = BNode(), BNode()
                Collection(g, head, [self.expression(one) for one in axiom.classes])
                g.add((node, RDF.type, OWL.AllDisjointClasses))
                g.add((node, OWL.members, head))
        elif isinstance(axiom, SubPropertyOf):
            if axiom.chain:
                head = BNode()
                Collection(g, head, [self.prop(one) for one in axiom.sub])
                g.add((self.prop(axiom.sup), OWL.propertyChainAxiom, head))
            else:
                g.add((self.prop(axiom.sub[0]), RDFS.subPropertyOf, self.prop(axiom.sup)))
        elif isinstance(axiom, EquivalentProperties):
            first = self.prop(axiom.properties[0])
            for other in axiom.properties[1:]:
                g.add((first, OWL.equivalentProperty, self.prop(other)))
        elif isinstance(axiom, DisjointProperties):
            first = self.prop(axiom.properties[0])
            for other in axiom.properties[1:]:
                g.add((first, OWL.propertyDisjointWith, self.prop(other)))
        elif isinstance(axiom, InverseProperties):
            g.add((self.prop(Property(name=axiom.first)), OWL.inverseOf,
                   self.prop(Property(name=axiom.second))))
        elif isinstance(axiom, Domain):
            g.add((self.prop(Property(name=axiom.property)), RDFS.domain,
                   self.expression(axiom.domain)))
        elif isinstance(axiom, Range):
            g.add((self.prop(Property(name=axiom.property)), RDFS.range,
                   self.expression(axiom.range)))
        elif isinstance(axiom, HasCharacteristic):
            kind = next(k for k, v in CHARACTERISTIC_TYPES.items() if v == axiom.characteristic)
            g.add((self.prop(Property(name=axiom.property)), RDF.type, kind))


__all__ = ["Projection", "Reader", "Unsupported", "declaration_order", "local_part",
           "to_graph", "to_turtle"]
