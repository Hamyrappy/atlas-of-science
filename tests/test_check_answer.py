"""Tests for reviewing an answer against the package it was written from.

The check that matters is the second one: an answer whose every line is cited, and whose
every citation is real, can still have turned a controversy into a consensus by leaving
one side out. That is invisible to the line-by-line rule and visible here. The other two
properties under test are that nothing is added -- the answer comes back exactly as it
went in -- and that a one-sided package answered one-sidedly is complete.
"""

from __future__ import annotations

from atlas.steps.answer import Answer
from atlas.steps.check_answer import check_answer
from atlas.steps.graph_expand import GraphExpandOptions, expand
from conftest import Fixture

POSITIONS = GraphExpandOptions(supports=("supports",), opposes=("disputes",), depth=3)


def package(science: Fixture, options: GraphExpandOptions = POSITIONS):
    return expand(science.store, [science.nodes["claim"].id], options)


def answered(*refs: str) -> Answer:
    return Answer(text="\n".join(f"a line [{ref}]" for ref in refs), citations=refs, hits=())


def test_an_answer_citing_both_sides_is_complete(science: Fixture) -> None:
    bundle = package(science)
    answer = answered(science.nodes["line-for"].ref, science.nodes["line-against"].ref)

    result = check_answer({"answer": answer, "bundle": bundle})

    assert result["review"].complete
    assert result["omissions"] == 0


def test_an_answer_citing_only_the_supporting_side_is_reported(science: Fixture) -> None:
    bundle = package(science)
    answer = answered(science.nodes["line-for"].ref)

    result = check_answer({"answer": answer, "bundle": bundle})

    assert result["review"].omitted == ("opposing",)
    assert not result["review"].complete


def test_an_answer_citing_only_the_opposing_side_is_reported(science: Fixture) -> None:
    bundle = package(science)
    answer = answered(science.nodes["line-against"].ref)

    result = check_answer({"answer": answer, "bundle": bundle})

    assert result["review"].omitted == ("supporting",)


def test_citing_the_claim_both_sides_point_at_counts_for_both(science: Fixture) -> None:
    bundle = package(science)
    answer = answered(science.nodes["claim"].ref)

    result = check_answer({"answer": answer, "bundle": bundle})

    # The claim is an end of both relations, which is how an answer to this kind of
    # question is actually written.
    assert result["review"].omitted == ()


def test_a_citation_that_resolves_to_nothing_is_reported(science: Fixture) -> None:
    bundle = package(science)
    answer = answered(science.nodes["claim"].ref, "paper-1#ffffff")

    result = check_answer({"answer": answer, "bundle": bundle})

    assert result["review"].unknown == ("paper-1#ffffff",)
    assert not result["review"].complete


def test_a_one_sided_package_answered_one_sidedly_is_complete(science: Fixture) -> None:
    bundle = package(science).model_copy(update={"opposing": ()})
    answer = answered(science.nodes["line-for"].ref)

    result = check_answer({"answer": answer, "bundle": bundle})

    assert result["review"].omitted == ()
    assert result["review"].complete


def test_a_partial_package_is_carried_into_the_review(science: Fixture) -> None:
    bundle = package(science, GraphExpandOptions(supports=("supports",),
                                                 opposes=("disputes",), depth=3, limit=2))
    answer = answered(science.nodes["claim"].ref)

    result = check_answer({"answer": answer, "bundle": bundle})

    assert result["review"].partial


def test_the_review_adds_nothing_to_the_answer(science: Fixture) -> None:
    bundle = package(science)
    answer = answered(science.nodes["line-for"].ref)

    result = check_answer({"answer": answer, "bundle": bundle})

    assert "answer" not in result
    assert answer.text == f"a line [{science.nodes['line-for'].ref}]"
