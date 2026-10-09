"""Tests for classifying the ontology a run is under.

Under test: the EL engine finds a subsumption nobody wrote as a parent and says whether it
read every axiom; the tableau finds a class empty that EL cannot, because the reason is a
union; a strict run stops on an empty class; and nothing here reads a node.
"""

from __future__ import annotations

import pytest

from atlas.ontology import load, load_text
from atlas.steps.classify import ClassifyOptions, classify

UNION = """
@prefix ex:   <https://example.org/u#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://example.org/u> a owl:Ontology .
ex:A a owl:Class ; rdfs:subClassOf [ a owl:Class ; owl:unionOf ( ex:B ex:C ) ] .
ex:B a owl:Class ; owl:disjointWith ex:A .
ex:C a owl:Class ; owl:disjointWith ex:A .
ex:D a owl:Class ; rdfs:subClassOf ex:B .
"""


def test_el_finds_what_a_definition_makes_a_subclass() -> None:
    result = classify({"schema": load("science_core_el")}, ClassifyOptions())

    # SupportingLine is defined, not given a parent by hand for this; EL derives it.
    assert "EvidenceLine" in result["hierarchy"]["SupportingLine"]
    assert result["classification"].engine == "el"
    assert result["unsatisfiable"] == ()


def test_el_says_it_is_incomplete_when_it_left_an_axiom_out() -> None:
    result = classify({"schema": load_text(UNION)}, ClassifyOptions())

    assert not result["classification"].complete
    assert any("ObjectUnionOf" in one for one in result["classification"].left_out)
    assert result["unsatisfiable"] == ()


def test_the_tableau_finds_a_class_empty_for_a_reason_el_cannot_read() -> None:
    result = classify({"schema": load_text(UNION)}, ClassifyOptions(engine="dl"))

    assert result["unsatisfiable"] == ("A",)
    assert result["hierarchy"]["D"] == ("B",)
    assert result["classification"].complete


def test_a_strict_run_stops_on_a_class_that_can_have_no_member() -> None:
    with pytest.raises(ValueError, match="can have no member: A"):
        classify({"schema": load_text(UNION)}, ClassifyOptions(engine="dl", strict=True))


def test_above_the_pairwise_limit_the_tableau_checks_satisfiability_only() -> None:
    result = classify({"schema": load_text(UNION)},
                      ClassifyOptions(engine="dl", pairwise_limit=1))

    assert result["unsatisfiable"] == ("A",)
    assert not result["classification"].complete
