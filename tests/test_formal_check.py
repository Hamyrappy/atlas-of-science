"""Tests for the gate a pack has to pass before anything is written under it.

The two decisions the module states are the two under test. A type nothing can be fails
the release although no instance exists, because the first instance would be a node that
cannot exist. And a check that was not run is reported as not run: a budget that stopped
the checking makes the report fail rather than pass, because "nothing was found" and
"nothing was looked for" are different answers.

Every pack this library ships is run through the gate here, which is the check that
keeps the shipped vocabulary honest as it grows.
"""

from __future__ import annotations

import pytest

from atlas.model import PredicateDef, Schema, TypeDef
from atlas.ontology import load
from atlas.steps.formal_check import CHECKS, FormalCheckOptions, formal_check, inspect

SHIPPED = [
    ("science_core",),
    ("science_core", "process"),
    ("science_core", "science_map"),
    ("science_core", "science_map", "scierc"),
    ("scierc",),
    ("ml_paper",),
]


def schema(*types: TypeDef, predicates: tuple[PredicateDef, ...] = ()) -> Schema:
    return Schema(version="0" * 12, types=types, predicates=predicates)


@pytest.mark.parametrize("packs", SHIPPED, ids=lambda packs: "+".join(packs))
def test_every_shipped_pack_passes_the_gate(packs: tuple[str, ...]) -> None:
    report = inspect(load(*packs))

    assert report.passed, [
        (one.kind, one.term, one.detail) for one in report.problems
    ]
    assert report.checked == CHECKS


def test_a_type_declared_disjoint_from_something_it_descends_from_is_reported() -> None:
    broken = schema(
        TypeDef(name="Thing"),
        TypeDef(name="Stuff", parent="Thing"),
        TypeDef(name="Impossible", parent="Stuff", disjoint_with=("Stuff",)),
    )

    report = inspect(broken)

    assert not report.passed
    assert any(one.kind == "self-disjoint" and one.term == "Impossible"
               for one in report.problems)


def test_a_class_nothing_instantiates_still_fails_the_release() -> None:
    broken = schema(
        TypeDef(name="Material"),
        TypeDef(name="Process", disjoint_with=("Material",)),
        TypeDef(name="Reagent", parent="Material", disjoint_with=("Material",)),
    )

    report = inspect(broken)

    # No node of Reagent exists anywhere; the pack is still broken.
    assert not report.passed
    assert {one.kind for one in report.problems} >= {"self-disjoint"}


def test_a_parent_that_does_not_exist_is_reported() -> None:
    report = inspect(schema(TypeDef(name="Thing", parent="Nowhere")))

    assert [one.kind for one in report.problems] == ["unknown-parent"]


def test_a_cycle_in_the_hierarchy_is_reported() -> None:
    report = inspect(schema(TypeDef(name="A", parent="B"), TypeDef(name="B", parent="A")))

    assert {one.kind for one in report.problems} == {"cycle"}


def test_a_relation_naming_a_type_that_does_not_exist_is_reported() -> None:
    report = inspect(schema(
        TypeDef(name="Thing"),
        predicates=(PredicateDef(name="r", domain="Thing", range="Nowhere"),),
    ))

    assert [one.kind for one in report.problems] == ["unknown-range"]


def test_a_characteristic_this_library_cannot_execute_is_reported() -> None:
    report = inspect(schema(
        TypeDef(name="Thing"),
        predicates=(PredicateDef(name="r", domain="Thing", range="Thing",
                                 characteristics=("reflexive",)),),
    ))

    assert [one.kind for one in report.problems] == ["unknown-characteristic"]


def test_a_transitive_relation_between_disjoint_types_can_never_compose() -> None:
    report = inspect(schema(
        TypeDef(name="A", disjoint_with=("B",)),
        TypeDef(name="B"),
        predicates=(PredicateDef(name="r", domain="A", range="B",
                                 characteristics=("transitive",)),),
    ))

    assert any(one.kind == "unsatisfiable" and one.term == "r" for one in report.problems)


def test_an_inverse_pair_that_does_not_mirror_is_reported() -> None:
    report = inspect(schema(
        TypeDef(name="A"),
        TypeDef(name="B"),
        predicates=(
            PredicateDef(name="f", domain="A", range="B"),
            PredicateDef(name="g", domain="A", range="B", inverse_of="f"),
        ),
    ))

    assert [one.kind for one in report.problems] == ["inverse-mismatch"]


def test_an_inverse_naming_nothing_is_reported() -> None:
    report = inspect(schema(
        TypeDef(name="A"),
        predicates=(PredicateDef(name="f", domain="A", range="A", inverse_of="missing"),),
    ))

    assert [one.kind for one in report.problems] == ["unknown-inverse"]


def test_a_check_that_was_not_run_is_reported_as_not_run() -> None:
    report = inspect(load("science_core"), budget=1)

    assert not report.passed
    assert report.problems == ()
    assert report.unchecked == CHECKS


def test_the_gate_stops_a_run_before_anything_is_written_under_a_broken_pack() -> None:
    broken = schema(TypeDef(name="Thing", parent="Nowhere"))

    with pytest.raises(ValueError, match="does not pass the formal gate"):
        formal_check({"schema": broken}, FormalCheckOptions())


def test_the_gate_can_report_instead_of_refusing() -> None:
    broken = schema(TypeDef(name="Thing", parent="Nowhere"))

    result = formal_check({"schema": broken}, FormalCheckOptions(strict=False))

    assert not result["formal"].passed
    assert len(result["problems"]) == 1


def test_a_pack_that_passes_leaves_a_report_saying_what_was_checked() -> None:
    result = formal_check({"schema": load("science_core")}, FormalCheckOptions())

    assert result["formal"].passed
    assert result["formal"].checked == CHECKS
    assert result["problems"] == ()
