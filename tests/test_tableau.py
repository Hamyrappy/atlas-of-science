"""The OWL 2 DL tableau: whether an ontology has a model, and which classes can have members.

Each test is an ontology with one way of being wrong, and the class that the mistake
leaves empty. Between them they exercise every rule the tableau has: disjunction,
existential and universal restrictions, a range and a domain absorbed into universals,
qualified cardinalities that force a merge and cardinalities that cannot be met, a
transitive relation and a chain walked by their automata, an inverse, disjoint relations
and a functional one. And the two things the gate depends on: a nominal is reported as not
decided rather than ignored, and a search over budget is unchecked, never passed.
"""

from __future__ import annotations

import pytest

from atlas.model.owl import (
    BOTTOM,
    And,
    Cardinality,
    DisjointClasses,
    DisjointProperties,
    Domain,
    EquivalentClasses,
    HasCharacteristic,
    HasValue,
    InverseProperties,
    Not,
    Only,
    Or,
    Property,
    Range,
    Some,
    SubClassOf,
    SubPropertyOf,
    named,
)
from atlas.ontology import load
from atlas.reason.tableau import decide, subsumed


def r(name: str, inverse: bool = False) -> Property:
    return Property(name=name, inverse=inverse)


def empty(axioms, name: str = "A") -> bool:  # noqa: ANN001
    return name in decide(axioms, [name]).unsatisfiable


CASES = {
    "a class disjoint from its own parent": [
        SubClassOf(sub=named("A"), sup=named("B")),
        DisjointClasses(classes=(named("A"), named("B")))],
    "a union whose every branch is excluded": [
        SubClassOf(sub=named("A"), sup=Or(operands=(named("S"), named("D")))),
        SubClassOf(sub=named("S"), sup=named("X")), SubClassOf(sub=named("D"), sup=named("X")),
        SubClassOf(sub=named("A"), sup=Not(operand=named("X")))],
    "an existential into an empty class": [
        SubClassOf(sub=named("A"), sup=Some(property=r("r"), filler=named("B"))),
        SubClassOf(sub=named("B"), sup=named(BOTTOM))],
    "a range disjoint from the filler": [
        SubClassOf(sub=named("A"), sup=Some(property=r("r"), filler=named("C"))),
        Range(property="r", range=named("D")),
        DisjointClasses(classes=(named("C"), named("D")))],
    "a domain reached through an inverse": [
        SubClassOf(sub=named("A"), sup=Some(property=r("r", True), filler=named("T"))),
        Domain(property="r", domain=named("C")),
        DisjointClasses(classes=(named("C"), named("T")))],
    "at least two and at most one": [
        SubClassOf(sub=named("A"), sup=Cardinality(bound="min", count=2, property=r("r"),
                                                   filler=named("C"))),
        SubClassOf(sub=named("A"), sup=Cardinality(bound="max", count=1, property=r("r"),
                                                   filler=named("C")))],
    "a transitive relation walked past its first step": [
        HasCharacteristic(property="p", characteristic="transitive"),
        SubClassOf(sub=named("A"), sup=And(operands=(
            Some(property=r("p"), filler=Some(property=r("p"), filler=named("Z"))),
            Only(property=r("p"), filler=Not(operand=named("Z"))))))],
    "a chain walked into the relation it implies": [
        SubPropertyOf(sub=(r("r"), r("s")), sup=r("t")),
        SubClassOf(sub=named("A"), sup=And(operands=(
            Some(property=r("r"), filler=Some(property=r("s"), filler=named("Z"))),
            Only(property=r("t"), filler=Not(operand=named("Z"))))))],
    "a universal read back along an inverse": [
        InverseProperties(first="p", second="q"),
        SubClassOf(sub=named("A"), sup=And(operands=(
            Some(property=r("p"), filler=Only(property=r("q"), filler=named("Z"))),
            Not(operand=named("Z")))))],
    "two disjoint relations on one edge": [
        DisjointProperties(properties=(r("s"), r("d"))),
        SubPropertyOf(sub=(r("x"),), sup=r("s")), SubPropertyOf(sub=(r("x"),), sup=r("d")),
        SubClassOf(sub=named("A"), sup=Some(property=r("x")))],
    "a functional relation forced to two disjoint values": [
        HasCharacteristic(property="f", characteristic="functional"),
        SubClassOf(sub=named("A"), sup=And(operands=(
            Some(property=r("f"), filler=named("C")), Some(property=r("f"), filler=named("D"))))),
        DisjointClasses(classes=(named("C"), named("D")))],
    "a definition met and denied at once": [
        EquivalentClasses(classes=(named("R"), And(operands=(
            named("S"), Some(property=r("c"), filler=named("T")))))),
        SubClassOf(sub=named("A"), sup=And(operands=(
            named("S"), Some(property=r("c"), filler=named("T")), Not(operand=named("R")))))],
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_way_of_being_wrong_leaves_the_class_empty(case: str) -> None:
    assert empty(CASES[case])


def test_a_class_that_can_have_members_is_not_reported() -> None:
    ok = [SubClassOf(sub=named("A"), sup=Cardinality(bound="min", count=1, property=r("r"),
                                                     filler=named("C"))),
          SubClassOf(sub=named("A"), sup=Cardinality(bound="max", count=1, property=r("r"),
                                                     filler=named("C"))),
          SubClassOf(sub=named("A"), sup=Some(property=r("r"), filler=named("A")))]
    verdict = decide(ok, ["A", "C"])
    assert verdict.consistent and verdict.unsatisfiable == () and verdict.decided


def test_a_nominal_is_reported_as_not_decided_rather_than_ignored() -> None:
    nominal = SubClassOf(sub=named("A"), sup=HasValue(property=r("r"), individual="x"))
    verdict = decide([nominal], ["A"])
    assert verdict.outside == (nominal,)
    assert not verdict.decided


def test_a_search_over_budget_is_unchecked_and_never_passed() -> None:
    wide = [SubClassOf(sub=named("A"), sup=Cardinality(bound="min", count=50, property=r("r")))]
    verdict = decide(wide, ["A"], max_nodes=10)
    assert verdict.consistent is True
    assert verdict.unchecked == ("A",) and not verdict.decided


def test_subsumption_is_unsatisfiability_of_the_difference() -> None:
    axioms = [SubClassOf(sub=named("A"), sup=named("B")),
              SubClassOf(sub=named("B"), sup=named("C"))]
    assert subsumed(named("A"), named("C"), axioms)
    assert not subsumed(named("C"), named("A"), axioms)


def test_the_shipped_dl_ontology_is_consistent_and_every_class_can_have_members() -> None:
    schema = load("science_core_dl", "process_rl", "science_map_rl")
    verdict = decide(schema.every_axiom(), [one.name for one in schema.types])
    assert verdict.consistent and verdict.decided
    assert verdict.unsatisfiable == ()
