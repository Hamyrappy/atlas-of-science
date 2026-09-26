"""Tests for telling a scientific disagreement apart from a mistake.

The rule under test is the conservative one: `disagreement` is what you get when nothing
else is established, and each of the other three verdicts has to be earned by something
the graph actually holds. The last test is the one that matters most -- reconciling a
conflict changes nothing in the store, because both positions are still there.
"""

from __future__ import annotations

from atlas.steps.graph_expand import GraphExpandOptions, expand
from atlas.steps.reconcile import ReconcileOptions, reconcile
from conftest import Fixture

OPTIONS = ReconcileOptions(supports=("supports",), opposes=("disputes",),
                           conditions=("observed_under",))


def state(science: Fixture, options: ReconcileOptions = OPTIONS) -> dict:
    return {
        "bundle": expand(science.store, [science.nodes["claim"].id],
                         GraphExpandOptions(depth=3, limit=40,
                                            supports=options.supports, opposes=options.opposes)),
        "store": science.store,
        "schema": science.schema,
    }


def test_two_positions_under_different_recorded_conditions_are_a_conditions_case(
    science: Fixture,
) -> None:
    [conflict] = reconcile(state(science), OPTIONS)["conflicts"]

    assert conflict.verdict == "conditions"
    assert "conditions" in conflict.conditions
    assert conflict.about == science.nodes["claim"].id


def test_one_source_taking_both_sides_under_the_same_conditions_is_ambiguous(
    science: Fixture,
) -> None:
    # Pointed at a relation that reaches no conditions, so nothing distinguishes the
    # two positions but the source -- and the source is the same paper.
    blind = ReconcileOptions(supports=("supports",), opposes=("disputes",),
                             conditions=("has_evidence_line",))

    [conflict] = reconcile(state(science, blind), blind)["conflicts"]

    assert conflict.verdict == "ambiguous"
    assert "both positions were cut from 'paper-1'" in conflict.reason
    assert conflict.settled


def test_a_package_with_only_one_side_has_no_conflict(science: Fixture) -> None:
    made = state(science)
    made["bundle"] = made["bundle"].model_copy(update={
        "links": tuple(link for link in made["bundle"].links if link.predicate != "disputes"),
    })

    assert reconcile(made, OPTIONS)["conflicts"] == ()


def test_a_disagreement_is_counted_and_never_resolved(science: Fixture) -> None:
    result = reconcile(state(science), OPTIONS)

    assert result["disagreements"] == 0  # this pair is explained by conditions
    assert len(result["conflicts"]) == 1


def test_reconciling_changes_nothing_in_the_store(science: Fixture) -> None:
    before = science.store.assertions()

    reconcile(state(science), OPTIONS)

    assert science.store.assertions() == before
    assert science.store.get_node(science.nodes["line-against"].id) is not None


def test_a_position_the_store_does_not_hold_is_ambiguous(science: Fixture) -> None:
    made = state(science)
    made["bundle"] = made["bundle"].model_copy(update={"nodes": ()})
    made["store"] = _Empty()

    [conflict] = reconcile(made, OPTIONS)["conflicts"]

    assert conflict.verdict == "ambiguous"
    assert "not in the store" in conflict.reason


class _Empty:
    """A store holding nothing, to stand for a package built against another snapshot."""

    def nodes(self):
        return ()

    def links(self):
        return ()


def test_a_positions_own_wording_is_not_a_condition_when_the_ontology_says_so(
    science: Fixture,
) -> None:
    """Where every class states itself in one shared field, two positions always differ in
    it -- that is what makes them two positions -- and counting it as a condition turns
    every disagreement into a "conditions" case."""
    worded = OPTIONS.model_copy(update={"fields": ("summary",), "conditions": ()})
    [by_wording] = reconcile(state(science, worded), worded)["conflicts"]
    assert by_wording.verdict == "conditions"
    assert "summary" in by_wording.conditions

    unworded = worded.model_copy(update={"own": False})
    [conflict] = reconcile(state(science, unworded), unworded)["conflicts"]
    assert "summary" not in conflict.conditions
