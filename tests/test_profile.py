"""The OWL 2 profiles: which one an ontology is in, and exactly which axioms keep it out.

A profile is the contract between an ontology and an engine, so what is under test is that
each contract is the one its engine needs: RL has no existential on the right, EL no
inverse, QL no transitive relation, RDFS nothing but the four entailments -- and all of
them are held to DL's global restrictions, so a transitive relation is never also
irreflexive, whatever the profile's own grammar would allow.
"""

from __future__ import annotations

import pytest

from atlas.model.owl import (
    DisjointClasses,
    Domain,
    HasCharacteristic,
    InverseProperties,
    Property,
    Some,
    SubClassOf,
    SubPropertyOf,
    named,
)
from atlas.reason.profile import explain, outside, profiles

EXISTS_RIGHT = SubClassOf(sub=named("A"), sup=Some(property=Property(name="r"), filler=named("B")))
TRANSITIVE = HasCharacteristic(property="r", characteristic="transitive")
INVERSE = InverseProperties(first="r", second="s")
PLAIN = [SubClassOf(sub=named("A"), sup=named("B")), Domain(property="r", domain=named("A"))]


def test_plain_hierarchy_and_signatures_are_in_every_profile() -> None:
    assert profiles(PLAIN) == ("RDFS", "EL", "QL", "RL", "DL")


def test_an_existential_on_the_right_is_not_rl_because_it_would_invent_something() -> None:
    assert outside([EXISTS_RIGHT], "RL") == [EXISTS_RIGHT]
    assert not outside([EXISTS_RIGHT], "EL") and not outside([EXISTS_RIGHT], "QL")


def test_an_inverse_is_not_el_and_transitivity_is_not_ql() -> None:
    assert outside([INVERSE], "EL") == [INVERSE]
    assert outside([TRANSITIVE], "QL") == [TRANSITIVE]


def test_disjointness_is_not_rdfs() -> None:
    disjoint = DisjointClasses(classes=(named("A"), named("B")))
    assert outside([disjoint], "RDFS") == [disjoint]


def test_a_composite_relation_may_not_be_irreflexive_in_any_profile() -> None:
    """The global restriction of OWL 2 DL, which every profile inherits."""
    irreflexive = HasCharacteristic(property="r", characteristic="irreflexive")
    for profile in ("RL", "DL"):
        assert outside([TRANSITIVE, irreflexive], profile) == [irreflexive]
    via_sub = [SubPropertyOf(sub=(Property(name="q"),), sup=Property(name="r")),
               HasCharacteristic(property="q", characteristic="transitive"), irreflexive]
    assert outside(via_sub, "DL") == [irreflexive]


def test_an_unknown_profile_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="OWL3"):
        outside(PLAIN, "OWL3")


def test_the_explanation_names_the_axioms_somebody_has_to_fix() -> None:
    assert "ObjectSomeValuesFrom(r B)" in explain([EXISTS_RIGHT], "RL")
    assert explain(PLAIN, "RL") == ""
