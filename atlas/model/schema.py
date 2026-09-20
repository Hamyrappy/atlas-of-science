"""The pluggable ontology: the types and predicates a body of nodes is written under.

The schema is data, not code. Nothing here names a type, a field or a predicate --
those arrive at run time from whatever file was loaded -- and nothing here reads a
file, because loading and merging belong to `atlas.ontology` and this module is
what everyone else may depend on.

Every term carries an optional IRI and mappings to public vocabularies, and is
looked up by its name or by its identity, CURIEs expanded through `prefixes`: a
label is local to one schema, an IRI survives the schema being replaced. Validation
returns a list of violations instead of raising, because a run scores the
markup it got rather than aborting on the first bad node.
"""

from __future__ import annotations

from pydantic import Field

from atlas.model.base import Frozen
from atlas.model.graph import Link, Node


class FieldDef(Frozen):
    """One field a type declares, and what a value of it means."""

    name: str
    datatype: str = "string"
    iri: str | None = None


class TypeDef(Frozen):
    """One node type: what it is called here, what it is, and what it says.

    `disjoint_with` names the types nothing may be both of. It is an axiom and not a
    hint: a pack that declares a type disjoint from one of its own ancestors has
    declared a type nothing can satisfy, and a step that checks the ontology before a
    release says so rather than waiting for the first node to be refused.
    """

    name: str
    iri: str | None = None
    parent: str | None = None
    fields: tuple[FieldDef, ...] = ()
    label_field: str | None = None  # which of the fields names the thing, for a reader
    mappings: tuple[str, ...] = ()
    disjoint_with: tuple[str, ...] = ()
    description: str = ""


TRANSITIVE = "transitive"
SYMMETRIC = "symmetric"
CHARACTERISTICS = (TRANSITIVE, SYMMETRIC)
"""What a pack may say about how a relation behaves, and the whole list of it.

Deliberately two: these are the only two a materialisation can close over without
either a reasoner or a decision about what to do when the closure stops terminating.
A pack that needs more is asking for a profile this library does not implement, and
saying so here is better than accepting the word and ignoring it.
"""


class PredicateDef(Frozen):
    """One relation type, with the node types it may connect and how it behaves.

    `characteristics` and `inverse_of` are the executable part of an RBox: what a
    materialisation may derive from an asserted link without asking anybody. Both are
    declared by the pack, so the core never learns that some particular relation is
    transitive -- only that a relation may say it is.
    """

    name: str
    domain: str
    range: str
    iri: str | None = None
    mappings: tuple[str, ...] = ()
    characteristics: tuple[str, ...] = ()
    inverse_of: str | None = None
    description: str = ""


class Schema(Frozen):
    """A version of one ontology: its terms, and the prefixes their CURIEs use.

    `version` is a content hash of whatever was loaded; it travels on every node and
    link, so an object written last month stays interpretable after today's edit.
    """

    version: str
    prefixes: dict[str, str] = Field(default_factory=dict)
    types: tuple[TypeDef, ...] = ()
    predicates: tuple[PredicateDef, ...] = ()

    def type_names(self) -> frozenset[str]:
        return frozenset(t.name for t in self.types)

    def find_type(self, term: str) -> TypeDef | None:
        """The type a term names, by local name or by identity."""
        return next((t for t in self.types if self._names(term, t.name, t.iri)), None)

    def find_predicate(self, term: str) -> PredicateDef | None:
        """The predicate a term names, by local name or by identity."""
        return next((p for p in self.predicates if self._names(term, p.name, p.iri)), None)

    def ancestry(self, term: str) -> tuple[TypeDef, ...]:
        """A type followed by its parents, nearest first; empty if the term is unknown."""
        chain: list[TypeDef] = []
        seen: set[str] = set()
        # A hand-written schema may declare a parent cycle, which loading need not catch.
        current = self.find_type(term)
        while current is not None and current.name not in seen:
            seen.add(current.name)
            chain.append(current)
            current = self.find_type(current.parent) if current.parent else None
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
        """Whether a type is the expected type or descends from it."""
        return any(self._names(expected, t.name, t.iri) for t in self.ancestry(term))

    def disjoint(self, term: str, other: str) -> bool:
        """Whether the pack forbids anything from being both of these types.

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
        """The predicates a pack declared to behave this way; unknown words match nothing."""
        return tuple(p for p in self.predicates if characteristic in p.characteristics)

    def inverse(self, term: str) -> PredicateDef | None:
        """The predicate declared as this one's inverse, from either side of the pair.

        A pack states the pair once, on whichever of the two it was more natural to
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
