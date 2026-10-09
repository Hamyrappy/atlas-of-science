"""The OWL 2 EL engine: every subsumption the axioms imply, and nothing they do not.

The rules under test are the ones the classifier stands on. A defined class is found
under what its definition makes it, through an existential and a role hierarchy. A range
narrows the filler of every existential over its relation. A transitive relation and a
chain carry a restriction as far as they reach. A class nothing can be is reported. And
what EL cannot read is returned, not ignored -- the answer is always true, and it is all
that is true exactly when nothing was left out.
"""

from __future__ import annotations

from atlas.model.owl import (
    And,
    DisjointClasses,
    EquivalentClasses,
    HasCharacteristic,
    Or,
    Property,
    Range,
    Some,
    SubClassOf,
    SubPropertyOf,
    named,
)
from atlas.ontology import load
from atlas.reason.el import classify


def r(name: str) -> Property:
    return Property(name=name)


def some(role: str, filler: str) -> Some:
    return Some(property=r(role), filler=named(filler))


def test_a_defined_class_is_found_under_what_its_definition_makes_it() -> None:
    result = classify([
        EquivalentClasses(classes=(named("Replicated"),
                                   And(operands=(named("Result"), some("confirmed_by", "Study"))))),
        SubClassOf(sub=named("Special"),
                   sup=And(operands=(named("Result"), some("confirmed_by", "Trial")))),
        SubClassOf(sub=named("Trial"), sup=named("Study")),
    ])
    assert "Replicated" in result.hierarchy()["Special"]
    assert result.complete


def test_a_range_narrows_the_filler_of_every_existential_over_its_relation() -> None:
    result = classify([
        Range(property="measures", range=named("Quantity")),
        SubClassOf(sub=named("Assay"), sup=Some(property=r("measures"))),
        SubClassOf(sub=some("measures", "Quantity"), sup=named("Measurement")),
    ])
    assert result.hierarchy()["Assay"] == ("Measurement",)


def test_transitivity_and_a_sub_relation_carry_a_restriction_as_far_as_they_reach() -> None:
    result = classify([
        HasCharacteristic(property="part_of", characteristic="transitive"),
        SubPropertyOf(sub=(r("part_of"),), sup=r("located_in")),
        SubClassOf(sub=named("Cell"), sup=some("part_of", "Organ")),
        SubClassOf(sub=named("Organ"), sup=some("part_of", "Body")),
        SubClassOf(sub=some("located_in", "Body"), sup=named("InBody")),
    ])
    assert "InBody" in result.hierarchy()["Cell"]


def test_a_chain_is_a_path_the_classifier_follows() -> None:
    result = classify([
        SubPropertyOf(sub=(r("derived_from"), r("used_dataset")), sup=r("rests_on_data")),
        SubClassOf(sub=named("R"), sup=some("derived_from", "C")),
        SubClassOf(sub=named("C"), sup=some("used_dataset", "D")),
        SubClassOf(sub=some("rests_on_data", "D"), sup=named("DataBacked")),
    ])
    assert "DataBacked" in result.hierarchy()["R"]


def test_a_class_nothing_can_be_is_reported() -> None:
    result = classify([
        DisjointClasses(classes=(named("Claim"), named("Study"))),
        SubClassOf(sub=named("Weird"), sup=And(operands=(named("Claim"), named("Study")))),
    ])
    assert result.unsatisfiable == {"Weird"}


def test_what_el_cannot_read_is_returned_and_what_it_can_is_still_used() -> None:
    union = SubClassOf(sub=named("X"), sup=Or(operands=(named("A"), named("B"))))
    split = SubClassOf(sub=Or(operands=(named("A"), named("B"))), sup=named("C"))
    result = classify([union, split])
    assert result.ignored == (union,)
    assert not result.complete
    # A union on the left is one axiom per disjunct, and both are EL.
    assert result.hierarchy()["A"] == ("C",)


def test_the_shipped_el_ontology_classifies_its_defined_classes() -> None:
    schema = load("science_core_el")
    assert schema.is_a("RecomputableResult", "StudyResult")
    assert schema.unsatisfiable == ()
