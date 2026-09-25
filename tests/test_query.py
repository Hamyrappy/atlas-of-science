"""Tests for answering a conjunctive query by rewriting it with the ontology.

Under test: a query over a relation the data never states directly is answered from the
relations the ontology puts under it; SQL and evaluation in memory give the same answers;
the answers are packaged by a walk, so a query is answered from a graph and not a table; a
query naming a word the ontology lacks is refused; and a consistency check reports what
breaks a disjointness without refusing the question.
"""

from __future__ import annotations

import pytest

from atlas.model import Agent, Assertion, Link
from atlas.steps.graph_expand import GraphExpandOptions
from atlas.steps.query import QueryOptions, query
from atlas.store.sqlite import SqliteStore
from conftest import Fixture

POSITIONS = GraphExpandOptions(depth=1, limit=40, supports=("supports",), opposes=("disputes",))
BEARING = "q(?line, ?claim) :- bears_on(?line, ?claim)"


def ask(science: Fixture, text: str = BEARING, store=None, **over) -> dict:  # noqa: ANN001
    return query({"store": store or science.store, "schema": science.schema},
                 QueryOptions(query=text, expand=POSITIONS, **over))


def test_a_relation_nobody_stated_is_answered_by_the_ones_the_ontology_puts_under_it(
    science: Fixture,
) -> None:
    result = ask(science)

    pairs = {one.values for one in result["answers"]}
    claim = science.nodes["claim"].id
    assert pairs == {(science.nodes["line-for"].id, claim),
                     (science.nodes["line-against"].id, claim)}
    assert {"q(?line, ?claim) :- supports(?line, ?claim)",
            "q(?line, ?claim) :- disputes(?line, ?claim)"} <= set(result["rewriting"])


def test_each_answer_carries_the_links_that_witnessed_it(science: Fixture) -> None:
    result = ask(science)

    witnessed = {link for one in result["answers"] for link in one.witnesses}
    assert witnessed == {science.links["line-for-supports-claim"].id,
                         science.links["line-against-disputes-claim"].id}


def test_the_answers_are_walked_into_a_package_with_the_objection_in_it(
    science: Fixture,
) -> None:
    bundle = ask(science)["bundle"]

    assert bundle.method == "query"
    assert bundle.grounded
    assert science.links["line-against-disputes-claim"].id in bundle.opposing


def test_sql_and_memory_give_the_same_answers(science: Fixture, tmp_path) -> None:  # noqa: ANN001
    store = SqliteStore(tmp_path / "atlas.db")
    for source in science.store.sources():
        store.add_source(source)
    for assertion in science.store.assertions():
        store.assert_(assertion)

    in_sql = {one.values for one in ask(science, store=store)["answers"]}
    in_memory = {one.values for one in ask(science, sql=False)["answers"]}

    assert in_sql == in_memory != set()


def test_a_query_naming_a_word_the_ontology_lacks_is_refused(science: Fixture) -> None:
    with pytest.raises(ValueError, match="no relation 'corroborates'"):
        ask(science, "q(?x) :- corroborates(?x, ?y)")
    with pytest.raises(ValueError, match="no class 'Hypothesis'"):
        ask(science, "q(?x) :- Hypothesis(?x)")


def test_a_consistency_check_reports_what_breaks_a_disjointness_and_still_answers(
    science: Fixture,
) -> None:
    # A computation recorded as supporting a claim: the domain of `supports` makes it an
    # information entity, and the ontology says no process is one.
    run, claim = science.nodes["run"], science.nodes["claim"]
    wrong = Link.of(predicate="supports", src=run.id, dst=claim.id, spans=claim.spans,
                    schema_version=science.schema.version)
    science.store.assert_(Assertion(id="wrong", agent=Agent(id="run", kind="run"),
                                    at="2026-01-01T00:00:00+00:00", target=wrong))

    result = ask(science, consistency=True)

    assert any(run.id in row for one in result["inconsistencies"] for row in one.rows)
    assert result["answers"]
