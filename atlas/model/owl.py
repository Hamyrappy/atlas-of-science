"""OWL 2 as values: the part of the structural specification this library reasons with.

An ontology here is a set of axioms, not a list of type names. `Schema.types` and
`Schema.predicates` are still what a step reads -- they are the vocabulary a prompt offers
and a configuration names -- but they are a *view* of the axioms below, and every engine
under `atlas/reason/` works on the axioms themselves.

The shape follows the OWL 2 structural specification (W3C, 2012) closely enough that a
reader of it can read this file: class expressions are built from named classes with
intersection, union, complement, existential and universal restriction, value and
cardinality restrictions; object property expressions are a property or its inverse;
axioms are the class, property and characteristic axioms of the TBox and RBox. Data
ranges and data property restrictions are not modelled, because nothing here reasons
over literals, and an ontology that uses them loads with those axioms reported as not
reasoned over rather than silently read wrong.

**Terms are referred to by the schema's own names.** A node's type is a name (`Result`),
a link's predicate is a name (`supports`), and an axiom is about the same names, so the
engines, the facts they reason over and the configuration that chose them agree on one
namespace. The identity of each name -- its IRI -- is on the `TypeDef` or `PredicateDef`
that declares it, and survives any renaming.

Nothing here reads a file or names a domain term. It is part of the metamodel because a
`Schema` carries its axioms: an object written under a schema version must stay
interpretable after the ontology it came from has been edited, and that includes what
the ontology implied about it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from atlas.model.base import Frozen

TOP = "owl:Thing"
BOTTOM = "owl:Nothing"
"""The two classes every ontology has without declaring them. Spelt as CURIEs because a
schema name never contains a colon, so neither can collide with a term somebody wrote."""

Characteristic = Literal[
    "transitive", "symmetric", "asymmetric", "reflexive", "irreflexive",
    "functional", "inverse-functional",
]
"""The object property characteristics of OWL 2. All seven parse; which of them an engine
executes is the engine's business, and each one says so."""


class Property(Frozen):
    """An object property expression: a named property, or the inverse of one."""

    name: str
    inverse: bool = False

    def inverted(self) -> Property:
        return Property(name=self.name, inverse=not self.inverse)

    def text(self) -> str:
        return f"ObjectInverseOf({self.name})" if self.inverse else self.name


# ---- class expressions ------------------------------------------------------------------


class Named(Frozen):
    kind: Literal["class"] = "class"
    name: str

    def text(self) -> str:
        return self.name


class And(Frozen):
    kind: Literal["and"] = "and"
    operands: tuple[ClassExpression, ...]

    def text(self) -> str:
        return f"ObjectIntersectionOf({' '.join(one.text() for one in self.operands)})"


class Or(Frozen):
    kind: Literal["or"] = "or"
    operands: tuple[ClassExpression, ...]

    def text(self) -> str:
        return f"ObjectUnionOf({' '.join(one.text() for one in self.operands)})"


class Not(Frozen):
    kind: Literal["not"] = "not"
    operand: ClassExpression

    def text(self) -> str:
        return f"ObjectComplementOf({self.operand.text()})"


class Some(Frozen):
    kind: Literal["some"] = "some"
    property: Property
    filler: ClassExpression = Named(name=TOP)

    def text(self) -> str:
        return f"ObjectSomeValuesFrom({self.property.text()} {self.filler.text()})"


class Only(Frozen):
    kind: Literal["only"] = "only"
    property: Property
    filler: ClassExpression

    def text(self) -> str:
        return f"ObjectAllValuesFrom({self.property.text()} {self.filler.text()})"


class HasValue(Frozen):
    kind: Literal["value"] = "value"
    property: Property
    individual: str

    def text(self) -> str:
        return f"ObjectHasValue({self.property.text()} {self.individual})"


class Cardinality(Frozen):
    kind: Literal["cardinality"] = "cardinality"
    bound: Literal["min", "max", "exactly"]
    count: int = Field(ge=0)
    property: Property
    filler: ClassExpression = Named(name=TOP)

    def text(self) -> str:
        name = {"min": "ObjectMinCardinality", "max": "ObjectMaxCardinality",
                "exactly": "ObjectExactCardinality"}[self.bound]
        return f"{name}({self.count} {self.property.text()} {self.filler.text()})"


ClassExpression = Annotated[
    Named | And | Or | Not | Some | Only | HasValue | Cardinality, Field(discriminator="kind")
]


def named(name: str) -> Named:
    return Named(name=name)


# ---- axioms -------------------------------------------------------------------------------


class SubClassOf(Frozen):
    kind: Literal["subclass"] = "subclass"
    sub: ClassExpression
    sup: ClassExpression

    def text(self) -> str:
        return f"SubClassOf({self.sub.text()} {self.sup.text()})"


class EquivalentClasses(Frozen):
    kind: Literal["equivalent-classes"] = "equivalent-classes"
    classes: tuple[ClassExpression, ...]

    def text(self) -> str:
        return f"EquivalentClasses({' '.join(one.text() for one in self.classes)})"


class DisjointClasses(Frozen):
    kind: Literal["disjoint-classes"] = "disjoint-classes"
    classes: tuple[ClassExpression, ...]

    def text(self) -> str:
        return f"DisjointClasses({' '.join(one.text() for one in self.classes)})"


class SubPropertyOf(Frozen):
    """`sub` of length one is a property inclusion; longer, it is a property chain."""

    kind: Literal["subproperty"] = "subproperty"
    sub: tuple[Property, ...]
    sup: Property

    @property
    def chain(self) -> bool:
        return len(self.sub) > 1

    def text(self) -> str:
        if self.chain:
            inner = " ".join(one.text() for one in self.sub)
            return f"SubObjectPropertyOf(ObjectPropertyChain({inner}) {self.sup.text()})"
        return f"SubObjectPropertyOf({self.sub[0].text()} {self.sup.text()})"


class EquivalentProperties(Frozen):
    kind: Literal["equivalent-properties"] = "equivalent-properties"
    properties: tuple[Property, ...]

    def text(self) -> str:
        return f"EquivalentObjectProperties({' '.join(one.text() for one in self.properties)})"


class DisjointProperties(Frozen):
    kind: Literal["disjoint-properties"] = "disjoint-properties"
    properties: tuple[Property, ...]

    def text(self) -> str:
        return f"DisjointObjectProperties({' '.join(one.text() for one in self.properties)})"


class InverseProperties(Frozen):
    kind: Literal["inverse"] = "inverse"
    first: str
    second: str

    def text(self) -> str:
        return f"InverseObjectProperties({self.first} {self.second})"


class Domain(Frozen):
    kind: Literal["domain"] = "domain"
    property: str
    domain: ClassExpression

    def text(self) -> str:
        return f"ObjectPropertyDomain({self.property} {self.domain.text()})"


class Range(Frozen):
    kind: Literal["range"] = "range"
    property: str
    range: ClassExpression

    def text(self) -> str:
        return f"ObjectPropertyRange({self.property} {self.range.text()})"


class HasCharacteristic(Frozen):
    kind: Literal["characteristic"] = "characteristic"
    property: str
    characteristic: Characteristic

    def text(self) -> str:
        name = {
            "transitive": "TransitiveObjectProperty", "symmetric": "SymmetricObjectProperty",
            "asymmetric": "AsymmetricObjectProperty", "reflexive": "ReflexiveObjectProperty",
            "irreflexive": "IrreflexiveObjectProperty",
            "functional": "FunctionalObjectProperty",
            "inverse-functional": "InverseFunctionalObjectProperty",
        }[self.characteristic]
        return f"{name}({self.property})"


Axiom = Annotated[
    SubClassOf | EquivalentClasses | DisjointClasses | SubPropertyOf | EquivalentProperties
    | DisjointProperties | InverseProperties | Domain | Range | HasCharacteristic,
    Field(discriminator="kind"),
]


for _model in (And, Or, Not, Some, Only, Cardinality, SubClassOf, EquivalentClasses,
               DisjointClasses, Domain, Range):
    _model.model_rebuild()


def signature(expression: ClassExpression) -> set[str]:
    """Every class name a class expression mentions, the two built-in ones included."""
    if isinstance(expression, Named):
        return {expression.name}
    if isinstance(expression, And | Or):
        return set().union(*(signature(one) for one in expression.operands))
    if isinstance(expression, Not):
        return signature(expression.operand)
    if isinstance(expression, Some | Only | Cardinality):
        return signature(expression.filler)
    return set()


def properties_of(expression: ClassExpression) -> set[str]:
    """Every object property a class expression mentions."""
    if isinstance(expression, And | Or):
        return set().union(*(properties_of(one) for one in expression.operands))
    if isinstance(expression, Not):
        return properties_of(expression.operand)
    if isinstance(expression, Some | Only | Cardinality):
        return {expression.property.name} | properties_of(expression.filler)
    if isinstance(expression, HasValue):
        return {expression.property.name}
    return set()


__all__ = [
    "BOTTOM",
    "TOP",
    "And",
    "Axiom",
    "Cardinality",
    "Characteristic",
    "ClassExpression",
    "DisjointClasses",
    "DisjointProperties",
    "Domain",
    "EquivalentClasses",
    "EquivalentProperties",
    "HasCharacteristic",
    "HasValue",
    "InverseProperties",
    "Named",
    "Not",
    "Only",
    "Or",
    "Property",
    "Range",
    "Some",
    "SubClassOf",
    "SubPropertyOf",
    "named",
    "properties_of",
    "signature",
]
