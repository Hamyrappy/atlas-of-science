"""Tests for the package every architecture builds and every answering step is given.

The guarantees under test are the three the module states: a package says whether it is
grounded, an objection survives a budget that everything else loses to, and which
relations count as a position comes from the configuration rather than from the code.
"""

from __future__ import annotations

from atlas.steps.graph_expand import Bundle, GraphExpandOptions, expand, graph_expand
from atlas.steps.retrieve import Hit
from conftest import Fixture

POSITIONS = GraphExpandOptions(supports=("supports",), opposes=("disputes",))


def test_the_walk_reaches_the_argument_behind_a_claim(science: Fixture) -> None:
    bundle = expand(science.store, [science.nodes["claim"].id], POSITIONS)

    reached = {node.id for node in bundle.nodes}
    assert science.nodes["line-for"].id in reached
    assert science.nodes["result-1"].id in reached
    assert bundle.grounded


def test_a_package_says_which_relations_carry_a_position(science: Fixture) -> None:
    bundle = expand(science.store, [science.nodes["claim"].id], POSITIONS)

    assert {link.predicate for link in bundle.links if link.id in bundle.supporting} == {"supports"}
    assert {link.predicate for link in bundle.links if link.id in bundle.opposing} == {"disputes"}


def test_the_names_of_the_positions_come_from_the_configuration(science: Fixture) -> None:
    bundle = expand(science.store, [science.nodes["claim"].id], GraphExpandOptions())

    # Nothing was named, so nothing is a position: the step does not know the pack.
    assert bundle.supporting == ()
    assert bundle.opposing == ()


def test_an_objection_survives_a_budget_that_everything_else_loses_to(science: Fixture) -> None:
    tight = GraphExpandOptions(supports=("supports",), opposes=("disputes",), limit=2, depth=3)

    bundle = expand(science.store, [science.nodes["claim"].id], tight)

    assert bundle.partial
    assert bundle.opposing != ()
    against = science.nodes["line-against"].id
    assert any(node.id == against for node in bundle.nodes)
    assert bundle.reasons[against] == "opposing disputes"


def test_a_package_with_no_relation_is_ungrounded_rather_than_empty(science: Fixture) -> None:
    alone = expand(science.store, [science.nodes["archive"].id],
                   GraphExpandOptions(depth=0), method="test")

    assert alone.nodes != ()
    assert not alone.grounded
    assert alone.method == "test"


def test_following_only_some_relations_drops_the_rest(science: Fixture) -> None:
    bundle = expand(science.store, [science.nodes["claim"].id],
                    GraphExpandOptions(follow=("states",), depth=3))

    assert {link.predicate for link in bundle.links} == {"states"}


def test_the_step_seeds_the_walk_from_the_ranking_and_records_why(science: Fixture) -> None:
    hits = (Hit(node=science.nodes["claim"], score=0.5),)

    state = graph_expand({"store": science.store, "hits": hits,
                          "schema": science.schema}, POSITIONS)

    bundle: Bundle = state["bundle"]
    assert bundle.roots == (science.nodes["claim"].id,)
    assert bundle.reasons[science.nodes["claim"].id] == "ranked 0.500"
    assert bundle.snapshot == science.schema.version
    assert len(bundle) == len(bundle.nodes)


def test_roots_come_first_so_a_reader_sees_what_was_asked_about(science: Fixture) -> None:
    bundle = expand(science.store, [science.nodes["result-1"].id], POSITIONS)

    assert bundle.nodes[0].id == science.nodes["result-1"].id
    assert bundle.refs()[0] == science.nodes["result-1"].ref
