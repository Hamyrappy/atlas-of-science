"""The pluggable ontology: the axioms a body of nodes is written under, and the view of them.

A `Schema` is two things at once, and it is worth keeping them apart.

**The ontology** is `axioms`: OWL 2 class, property and characteristic axioms
(`atlas.model.owl`), which is what every engine under `atlas/reason/` reasons with. They
arrive from an ontology file -- Turtle, RDF/XML, JSON-LD, or a legacy YAML pack compiled
into the same axioms -- and nothing here names one of their terms.

**The vocabulary** is `types` and `predicates`: what a prompt offers a model, what a
configuration names, what a validator checks a node against. It is a projection of the
axioms -- each named class with its told parent, fields and identity, each object
property with its domain, range and characteristics -- and `hierarchy` is the class
hierarchy a reasoner computed from the axioms, which is what `is_a` answers from. A
schema built by hand from `types` and `predicates` alone, as tests and small tools do,
still works: `every_axiom` derives the axioms that projection states, so the engines see
the same thing either way.

Every term carries an optional IRI and mappings to public vocabularies, and is looked up
by its name or by its identity, CURIEs expanded through `prefixes`: a label is local to one
schema, an IRI survives the schema being replaced. Validation returns a list of violations
instead of raising, because a run scores the markup it got rather than aborting on the
first bad node.
"""

from __future__ import annotations

from pydantic import Field

from atlas.model.base import Frozen
from atlas.model.graph import Link, Node
from atlas.model.owl import (
    TOP,
    Axiom,
    DisjointClasses,
    Domain,
    HasCharacteristic,
    InverseProperties,
    Named,
    Property,
    Range,
    SubClassOf,
    SubPropertyOf,
)


class FieldDef(Frozen):
    """One field a type declares, and what a value of it means."""

    name: str
    datatype: str = "string"
    iri: str | None = None


class TypeDef(Frozen):
    """One node type: what it is called here, what it is, and what it says.

    `disjoint_with` names the types nothing may be both of. It is an axiom and not a
    hint: an ontology that declares a type disjoint from one of its own ancestors has
    declared a type nothing can satisfy, and a step that checks the ontology before a
    release says so rather than waiting for the first node to be refused.

    `defined` marks a class whose members an engine works out -- "a line of evidence
    that supports some proposition" -- and that an extractor is therefore never offered.
    Asking a model to label something the ontology decides would be asking it to guess
    what the axioms already say.
    """

    name: str
    iri: str | None = None
    parent: str | None = None
    fields: tuple[FieldDef, ...] = ()
    label_field: str | None = None  # which of the fields names the thing, for a reader
    mappings: tuple[str, ...] = ()
    disjoint_with: tuple[str, ...] = ()
    description: str = ""
    defined: bool = Field(
        default=False,
        description="Membership is inferred from the ontology's axioms, never asked of a model",
    )


TRANSITIVE = "transitive"
SYMMETRIC = "symmetric"
CHARACTERISTICS = (
    TRANSITIVE, SYMMETRIC, "asymmetric", "reflexive", "irreflexive", "functional",
    "inverse-functional",
)
"""What an ontology may say about how a relation behaves: the seven characteristics of
OWL 2, and nothing else. Which of them an engine executes is the engine's to say --
the OWL 2 RL engine executes all but `reflexive`, which would type every individual
and is outside that profile -- and a word outside this list is refused when the
ontology is checked rather than accepted and ignored."""


class PredicateDef(Frozen):
    """One relation type, with the node types it may connect and how it behaves.

    `characteristics`, `inverse_of` and `parents` are the RBox as a configuration reads it:
    what a materialisation may derive from an asserted link without asking anybody. All of
    them are declared by the ontology, so the core never learns that some particular
    relation is transitive -- only that a relation may say it is. A domain or range left
    as `owl:Thing` says nothing, which is what an ontology that declares none means.
    """

    name: str
    domain: str = TOP
    range: str = TOP
    iri: str | None = None
    mappings: tuple[str, ...] = ()
    characteristics: tuple[str, ...] = ()
    inverse_of: str | None = None
    parents: tuple[str, ...] = Field(
        default=(), description="Properties this one is declared a sub-property of"
    )
    description: str = ""


class Schema(Frozen):
    """A version of one ontology: its axioms, the vocabulary they project, and its prefixes.

    `version` is a content hash of whatever was loaded; it travels on every node and
    link, so an object written last month stays interpretable after today's edit --
    including what the ontology implied about it, which is why the axioms travel too.

    `profile` is the OWL 2 profile the configuration requires the ontology to stay
    within (`RDFS`, `EL`, `QL`, `RL` or `DL`), empty for none; the loader refuses an
    ontology that leaves it. `shapes` is the Turtle of the SHACL shapes the configuration
    named, the closed-world half of the ontology: what a node must carry, as opposed to
    what may be inferred about it.
    """

    version: str
    iri: str = ""
    prefixes: dict[str, str] = Field(default_factory=dict)
    types: tuple[TypeDef, ...] = ()
    predicates: tuple[PredicateDef, ...] = ()
    axioms: tuple[Axiom, ...] = ()
    hierarchy: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description="Every named superclass of each named class, as a reasoner computed it",
    )
    unsatisfiable: tuple[str, ...] = Field(
        default=(), description="Named classes the reasoner found can have no instance"
    )
    profile: str = ""
    shapes: str = ""
    imports: tuple[str, ...] = Field(
        default=(), description="Ontologies imported by IRI and not available to load"
    )
    unread: tuple[str, ...] = Field(
        default=(),
        description="What the ontology states that no engine here models, by its triple",
    )

    def every_axiom(self) -> tuple[Axiom, ...]:
        """The axioms, together with every one the vocabulary states and they do not.

        An ontology loaded from a file has both, and they agree. A schema written by hand
        as types and predicates has only the second, and this is what lets every engine
        reason over it anyway: a told parent is a subclass axiom, a declared domain is a
        domain axiom, a characteristic is a characteristic.
        """
        seen = set(self.axioms)
        extra: list[Axiom] = []
        for axiom in self._stated():
            if axiom not in seen:
                seen.add(axiom)
                extra.append(axiom)
        return (*self.axioms, *extra)

    def _stated(self) -> list[Axiom]:
        stated: list[Axiom] = []
        for type_def in self.types:
            if type_def.parent:
                stated.append(SubClassOf(sub=Named(name=type_def.name),
                                         sup=Named(name=self._name_of(type_def.parent))))
            for other in type_def.disjoint_with:
                pair = sorted((type_def.name, self._name_of(other)))
                stated.append(DisjointClasses(classes=tuple(Named(name=n) for n in pair)))
        for predicate in self.predicates:
            if predicate.domain and self._name_of(predicate.domain) != TOP:
                stated.append(Domain(property=predicate.name,
                                     domain=Named(name=self._name_of(predicate.domain))))
            if predicate.range and self._name_of(predicate.range) != TOP:
                stated.append(Range(property=predicate.name,
                                    range=Named(name=self._name_of(predicate.range))))
            stated += [HasCharacteristic(property=predicate.name, characteristic=named)
                       for named in predicate.characteristics if named in CHARACTERISTICS]
            if predicate.inverse_of:
                stated.append(InverseProperties(
                    first=predicate.name, second=self._property_name(predicate.inverse_of)
                ))
            stated += [SubPropertyOf(sub=(Property(name=predicate.name),),
                                     sup=Property(name=self._property_name(parent)))
                       for parent in predicate.parents]
        return stated

    def _name_of(self, term: str) -> str:
        found = self.find_type(term)
        return found.name if found is not None else term

    def _property_name(self, term: str) -> str:
        found = self.find_predicate(term)
        return found.name if found is not None else term

    def type_names(self) -> frozenset[str]:
        return frozenset(t.name for t in self.types)

    def find_type(self, term: str) -> TypeDef | None:
        """The type a term names, by local name or by identity."""
        return next((t for t in self.types if self._names(term, t.name, t.iri)), None)

    def find_predicate(self, term: str) -> PredicateDef | None:
        """The predicate a term names, by local name or by identity."""
        return next((p for p in self.predicates if self._names(term, p.name, p.iri)), None)

    def ancestry(self, term: str) -> tuple[TypeDef, ...]:
        """A type followed by its superclasses: the told parents nearest first, then the
        ones only a reasoner found. Empty if the term is unknown.

        Told parents first because they are the order a person wrote -- and the order in
        which fields are inherited and a label is looked for. The inferred ones follow,
        because a class the ontology *implies* is a superclass is one whose fields and
        disjointness apply just as much.
        """
        chain: list[TypeDef] = []
        seen: set[str] = set()
        # A hand-written schema may declare a parent cycle, which loading need not catch.
        current = self.find_type(term)
        while current is not None and current.name not in seen:
            seen.add(current.name)
            chain.append(current)
            current = self.find_type(current.parent) if current.parent else None
        if chain:
            for name in self.hierarchy.get(chain[0].name, ()):
                found = self.find_type(name)
                if found is not None and found.name not in seen:
                    seen.add(found.name)
                    chain.append(found)
        return tuple(chain)

    def declared_fields(self, term: str) -> tuple[FieldDef, ...]:
        """The fields a type declares, then the ones it inherits, without repeats."""
        fields: list[FieldDef] = []
        taken: set[str] = set()
        for type_def in self.ancestry(term):
            for field in type_def.fields:
                if field.name not in taken:
                    taken.add(field.name)
                    fields.append(field)
        return tuple(fields)

    def label_of(self, node: Node) -> str:
        """What to call this node in front of a person.

        The type says which of its fields names the thing; one that does not say falls
        back to the first field it declares, and a node that filled in neither falls
        back to its type. Never the id, which is a content hash.
        """
        labelled = next((t for t in self.ancestry(node.type) if t.label_field), None)
        preferred = [labelled.label_field] if labelled else []
        for name in preferred + [f.name for f in self.declared_fields(node.type)]:
            if node.fields.get(name):
                return node.fields[name]
        return node.type

    def validate_node(self, node: Node) -> list[str]:
        """Everything wrong with a node under this schema; empty means valid."""
        violations: list[str] = []
        if self.find_type(node.type) is None:
            violations.append(f"node {node.id}: unknown type {node.type!r}")
        else:
            declared = {field.name for field in self.declared_fields(node.type)}
            violations.extend(
                f"node {node.id}: field {key!r} is not declared on type {node.type!r}"
                for key in node.fields
                if key not in declared
            )
        # Node and Span already guarantee at least one span and non-empty span text, so
        # the only provenance defect that can reach here is text that is all whitespace.
        violations.extend(
            f"node {node.id}: blank span at {span.source_id} segment {span.segment}"
            for span in node.spans
            if not span.text.strip()
        )
        return violations

    def validate_link(self, link: Link, src_type: str, dst_type: str) -> list[str]:
        """Everything wrong with a link, given the types of the nodes it joins."""
        predicate = self.find_predicate(link.predicate)
        if predicate is None:
            return [f"link {link.id}: unknown predicate {link.predicate!r}"]
        violations: list[str] = []
        if not self.is_a(src_type, predicate.domain):
            violations.append(
                f"link {link.id}: predicate {predicate.name!r} "
                f"expects domain {predicate.domain!r}, source is {src_type!r}"
            )
        if not self.is_a(dst_type, predicate.range):
            violations.append(
                f"link {link.id}: predicate {predicate.name!r} "
                f"expects range {predicate.range!r}, target is {dst_type!r}"
            )
        return violations

    def is_a(self, term: str, expected: str) -> bool:
        """Whether a type is the expected type or is subsumed by it.

        Answered from the reasoner's hierarchy where the loader computed one, so a class
        the axioms make a subclass -- through an equivalence, an intersection, an
        existential restriction -- is one without anybody having written it as a parent.
        Everything is a `owl:Thing`, and an unsatisfiable class is subsumed by everything,
        which is exactly why the loader reports one rather than letting it be used.
        """
        if expected == TOP:
            return self.find_type(term) is not None or term == TOP
        if term in self.unsatisfiable:
            return True
        return any(self._names(expected, t.name, t.iri) for t in self.ancestry(term))

    def subproperties(self, term: str) -> tuple[str, ...]:
        """A property and every property the axioms make a sub-property of it, the property
        first. Chains are left out: a chain is not a property one can follow by name."""
        wanted = self._property_name(term)
        below: dict[str, set[str]] = {}
        for axiom in self.every_axiom():
            if isinstance(axiom, SubPropertyOf) and not axiom.chain:
                sub, sup = axiom.sub[0], axiom.sup
                if not sub.inverse and not sup.inverse:
                    below.setdefault(sup.name, set()).add(sub.name)
        found, frontier = [wanted], [wanted]
        while frontier:
            current = frontier.pop()
            for sub in sorted(below.get(current, ())):
                if sub not in found:
                    found.append(sub)
                    frontier.append(sub)
        return tuple(found)

    def disjoint(self, term: str, other: str) -> bool:
        """Whether the ontology forbids anything from being both of these types.

        Disjointness is inherited downwards: a type declared disjoint from one is
        disjoint from everything under it, which is what makes the axiom worth
        declaring once on the pair of roots rather than on every pair of leaves.
        """
        return any(
            self.is_a(other, named)
            for ancestor in self.ancestry(term)
            for named in ancestor.disjoint_with
        ) or any(
            self.is_a(term, named)
            for ancestor in self.ancestry(other)
            for named in ancestor.disjoint_with
        )

    def with_characteristic(self, characteristic: str) -> tuple[PredicateDef, ...]:
        """The predicates an ontology declared to behave this way; unknown words match nothing."""
        return tuple(p for p in self.predicates if characteristic in p.characteristics)

    def inverse(self, term: str) -> PredicateDef | None:
        """The predicate declared as this one's inverse, from either side of the pair.

        An ontology states the pair once, on whichever of the two it was more natural to
        write it on, and both directions answer -- otherwise half of every inverse
        would be derivable and the other half silently not.
        """
        predicate = self.find_predicate(term)
        if predicate is None:
            return None
        if predicate.inverse_of:
            return self.find_predicate(predicate.inverse_of)
        return next(
            (p for p in self.predicates if p.inverse_of and self._names(p.inverse_of,
                                                                       predicate.name,
                                                                       predicate.iri)),
            None,
        )

    def _names(self, term: str, name: str, iri: str | None) -> bool:
        """Whether a term refers to a definition: its local name, or its identity."""
        return term == name or (iri is not None and self.expand(term) == self.expand(iri))

    def expand(self, term: str) -> str:
        """A CURIE resolved against the prefixes of this schema; anything else unchanged."""
        prefix, separator, rest = term.partition(":")
        base = self.prefixes.get(prefix) if separator else None
        return f"{base}{rest}" if base is not None else term
