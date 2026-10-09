"""Which OWL 2 profile an ontology is in, and exactly which axioms keep it out of the others.

A profile is a contract between an ontology and an engine. OWL 2 defines three tractable
ones (W3C, OWL 2 Profiles, 2012) and each exists because of what an engine can then
guarantee: **EL** classifies completely in polynomial time; **QL** answers a query over
data by rewriting it, without materialising anything, which is what lets a relational
store answer it; **RL** runs as rules over data and never invents an individual. **DL** is
the whole decidable language, and **RDFS** here names the four entailments an RDFS engine
performs -- subclass, sub-property, domain and range -- and nothing else.

An architecture names the profile its ontology must stay within, and the loader refuses an
ontology that leaves it. That is stricter than most systems, which reason over whatever
part of an ontology their engine understands and say nothing about the rest. The reason
for the strictness is the thing being measured: an architecture's answers are compared
with another's, and if one of them was silently reasoning over a different ontology from
the one its configuration names, the comparison is between two ontologies wearing the
names of two architectures.

`outside` returns the axioms that break the contract, never just a yes or no, because
"this axiom is not RL: it has an existential on the right" is what somebody fixing the
ontology needs to read.

The checks follow the grammars of the profiles' specification for the constructs the
structural model has. The one simplification is on DL's global restrictions: simple
properties are checked where the specification requires them (cardinality, functional,
irreflexive, asymmetric, disjoint), and the regularity of the property hierarchy is not.
"""

from __future__ import annotations

from collections.abc import Iterable

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
    Range,
    Some,
    SubClassOf,
    SubPropertyOf,
)

PROFILES = ("RDFS", "EL", "QL", "RL", "DL")


def outside(axioms: Iterable[Axiom], profile: str) -> list[Axiom]:
    """Every axiom that is not in the named profile, in the order given."""
    axioms = list(axioms)
    if profile not in PROFILES:
        raise ValueError(f"no profile {profile!r}; the profiles are {', '.join(PROFILES)}")
    # The three tractable profiles are syntactic subsets of OWL 2 DL, so an ontology in
    # one of them is held to DL's global restrictions as well: a transitive relation
    # cannot also be irreflexive, whatever the profile's own grammar allows.
    composite = _non_simple(axioms)
    if profile == "DL":
        return [one for one in axioms if not _dl(one, composite)]
    check = {"RDFS": _rdfs, "EL": _el, "QL": _ql, "RL": _rl}[profile]
    return [one for one in axioms if not (check(one) and _dl(one, composite))]


def profiles(axioms: Iterable[Axiom]) -> tuple[str, ...]:
    """Every profile the axioms are entirely within, from the most restrictive."""
    axioms = list(axioms)
    return tuple(name for name in PROFILES if not outside(axioms, name))


def explain(axioms: Iterable[Axiom], profile: str, limit: int = 5) -> str:
    """The first few axioms outside a profile, as a sentence somebody can act on."""
    found = outside(axioms, profile)
    if not found:
        return ""
    shown = "; ".join(one.text() for one in found[:limit])
    more = f"; and {len(found) - limit} more" if len(found) > limit else ""
    return f"{len(found)} axiom(s) outside OWL 2 {profile}: {shown}{more}"


# ---- RDFS ---------------------------------------------------------------------------------


def _rdfs(axiom: Axiom) -> bool:
    if isinstance(axiom, SubClassOf):
        return _plain(axiom.sub) and _plain(axiom.sup)
    if isinstance(axiom, SubPropertyOf):
        return not axiom.chain and not axiom.sub[0].inverse and not axiom.sup.inverse
    if isinstance(axiom, Domain):
        return _plain(axiom.domain)
    if isinstance(axiom, Range):
        return _plain(axiom.range)
    return False


def _plain(expression: ClassExpression) -> bool:
    return isinstance(expression, Named) and expression.name not in (TOP, BOTTOM)


# ---- EL -----------------------------------------------------------------------------------


def _el_class(expression: ClassExpression) -> bool:
    if isinstance(expression, Named):
        return True
    if isinstance(expression, And):
        return all(_el_class(one) for one in expression.operands)
    if isinstance(expression, Some):
        return not expression.property.inverse and _el_class(expression.filler)
    if isinstance(expression, HasValue):
        return not expression.property.inverse
    return False


def _el(axiom: Axiom) -> bool:
    if isinstance(axiom, SubClassOf):
        return _el_class(axiom.sub) and _el_class(axiom.sup)
    if isinstance(axiom, EquivalentClasses | DisjointClasses):
        return all(_el_class(one) for one in axiom.classes)
    if isinstance(axiom, SubPropertyOf):
        return not any(one.inverse for one in (*axiom.sub, axiom.sup))
    if isinstance(axiom, EquivalentProperties):
        return not any(one.inverse for one in axiom.properties)
    if isinstance(axiom, Domain):
        return _el_class(axiom.domain)
    if isinstance(axiom, Range):
        return _el_class(axiom.range)
    if isinstance(axiom, HasCharacteristic):
        return axiom.characteristic in ("transitive", "reflexive")
    return False


# ---- QL -----------------------------------------------------------------------------------


def _ql_sub(expression: ClassExpression) -> bool:
    if isinstance(expression, Named):
        return expression.name != BOTTOM
    if isinstance(expression, Some):
        filler = expression.filler
        return isinstance(filler, Named) and filler.name == TOP
    return False


def _ql_sup(expression: ClassExpression) -> bool:
    if isinstance(expression, Named):
        return True
    if isinstance(expression, And):
        return all(_ql_sup(one) for one in expression.operands)
    if isinstance(expression, Not):
        return _ql_sub(expression.operand)
    if isinstance(expression, Some):
        return isinstance(expression.filler, Named)
    return False


def _ql(axiom: Axiom) -> bool:
    if isinstance(axiom, SubClassOf):
        return _ql_sub(axiom.sub) and _ql_sup(axiom.sup)
    if isinstance(axiom, EquivalentClasses | DisjointClasses):
        return all(_ql_sub(one) for one in axiom.classes)
    if isinstance(axiom, SubPropertyOf):
        return not axiom.chain
    if isinstance(axiom, EquivalentProperties | DisjointProperties | InverseProperties):
        return True
    if isinstance(axiom, Domain):
        return _ql_sup(axiom.domain)
    if isinstance(axiom, Range):
        return _ql_sup(axiom.range)
    if isinstance(axiom, HasCharacteristic):
        return axiom.characteristic in ("symmetric", "asymmetric", "reflexive", "irreflexive")
    return False


# ---- RL -----------------------------------------------------------------------------------


def _rl_sub(expression: ClassExpression) -> bool:
    if isinstance(expression, Named):
        return expression.name != TOP
    if isinstance(expression, And | Or):
        return all(_rl_sub(one) for one in expression.operands)
    if isinstance(expression, Some):
        filler = expression.filler
        return (isinstance(filler, Named) and filler.name == TOP) or _rl_sub(filler)
    return isinstance(expression, HasValue)


def _rl_sup(expression: ClassExpression) -> bool:
    if isinstance(expression, Named):
        return expression.name != TOP
    if isinstance(expression, And):
        return all(_rl_sup(one) for one in expression.operands)
    if isinstance(expression, Not):
        return _rl_sub(expression.operand)
    if isinstance(expression, Only):
        return _rl_sup(expression.filler)
    if isinstance(expression, HasValue):
        return True
    if isinstance(expression, Cardinality):
        filler = expression.filler
        return (expression.bound == "max" and expression.count <= 1
                and ((isinstance(filler, Named) and filler.name == TOP) or _rl_sub(filler)))
    return False


def _rl_equivalent(expression: ClassExpression) -> bool:
    if isinstance(expression, Named):
        return expression.name != TOP
    if isinstance(expression, And):
        return all(_rl_equivalent(one) for one in expression.operands)
    return isinstance(expression, HasValue)


def _rl(axiom: Axiom) -> bool:
    if isinstance(axiom, SubClassOf):
        return _rl_sub(axiom.sub) and _rl_sup(axiom.sup)
    if isinstance(axiom, EquivalentClasses):
        return all(_rl_equivalent(one) for one in axiom.classes)
    if isinstance(axiom, DisjointClasses):
        return all(_rl_sub(one) for one in axiom.classes)
    if isinstance(axiom, SubPropertyOf | EquivalentProperties | DisjointProperties
                  | InverseProperties):
        return True
    if isinstance(axiom, Domain):
        return _rl_sup(axiom.domain)
    if isinstance(axiom, Range):
        return _rl_sup(axiom.range)
    if isinstance(axiom, HasCharacteristic):
        return axiom.characteristic != "reflexive"
    return False


# ---- DL -----------------------------------------------------------------------------------


def _non_simple(axioms: list[Axiom]) -> set[str]:
    """The properties a cardinality or a functional axiom may not use: the composite ones.

    A property is non-simple when it is transitive, is the super-property of a chain, or
    has a non-simple sub-property. Restricting those is what OWL 2 DL forbids, because it
    is what makes reasoning undecidable.
    """
    composite = {one.property for one in axioms
                 if isinstance(one, HasCharacteristic) and one.characteristic == "transitive"}
    composite |= {one.sup.name for one in axioms if isinstance(one, SubPropertyOf) and one.chain}
    above: dict[str, set[str]] = {}
    for one in axioms:
        if isinstance(one, SubPropertyOf) and not one.chain:
            above.setdefault(one.sub[0].name, set()).add(one.sup.name)
        elif isinstance(one, InverseProperties):
            # The inverse of a composite relation is composite: if part_of chains, so
            # does has_part, read the other way.
            above.setdefault(one.first, set()).add(one.second)
            above.setdefault(one.second, set()).add(one.first)
    growing = True
    while growing:
        growing = False
        for sub, sups in above.items():
            if sub in composite:
                for sup in sups:
                    if sup not in composite:
                        composite.add(sup)
                        growing = True
    return composite


def _cardinalities(expression: ClassExpression) -> list[Cardinality]:
    if isinstance(expression, Cardinality):
        return [expression, *_cardinalities(expression.filler)]
    if isinstance(expression, And | Or):
        return [c for one in expression.operands for c in _cardinalities(one)]
    if isinstance(expression, Not):
        return _cardinalities(expression.operand)
    if isinstance(expression, Some | Only):
        return _cardinalities(expression.filler)
    return []


def _dl(axiom: Axiom, composite: set[str]) -> bool:
    if isinstance(axiom, HasCharacteristic):
        return not (axiom.characteristic in ("functional", "inverse-functional", "irreflexive",
                                             "asymmetric") and axiom.property in composite)
    if isinstance(axiom, DisjointProperties):
        return not any(one.name in composite for one in axiom.properties)
    expressions: list[ClassExpression] = []
    if isinstance(axiom, SubClassOf):
        expressions = [axiom.sub, axiom.sup]
    elif isinstance(axiom, EquivalentClasses | DisjointClasses):
        expressions = list(axiom.classes)
    elif isinstance(axiom, Domain):
        expressions = [axiom.domain]
    elif isinstance(axiom, Range):
        expressions = [axiom.range]
    return not any(c.property.name in composite
                   for expression in expressions for c in _cardinalities(expression))


__all__ = ["PROFILES", "explain", "outside", "profiles"]
