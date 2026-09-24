"""The OWL 2 QL engine: certain answers by rewriting, over what is literally stored.

Under test: a query is rewritten through sub-classes, sub-relations, inverses, domains,
ranges and existentials, and evaluating the rewriting over stored rows gives the answers
the ontology and the data together imply; an unbound place is what lets an existential
answer; a negative inclusion becomes a query for what breaks it; and the SQL a rewriting
compiles to returns the same rows as evaluating it in memory.
"""

from __future__ import annotations

import pytest

from atlas.model import Link, Node, Segment, Source, Span
from atlas.model.owl import (
    DisjointClasses,
    Domain,
    InverseProperties,
    Property,
    Range,
    Some,
    SubClassOf,
    SubPropertyOf,
    named,
)
from atlas.ontology import load
from atlas.reason.ql import evaluate, parse, rewrite, tbox, to_sql, violations
from atlas.store.sqlite import SqliteStore

TEXT = "a quote long enough to stand on"
SOURCE = Source(id="s", origin="s.txt", segments=(Segment(number=1, text=TEXT),))
SPAN = (Span.of(SOURCE, 1, 0, 7),)


def node(node_id: str, type_name: str) -> Node:
    return Node(id=node_id, type=type_name, spans=SPAN, schema_version="v")


def link(link_id: str, predicate: str, src: str, dst: str) -> Link:
    return Link(id=link_id, predicate=predicate, src=src, dst=dst, spans=SPAN, schema_version="v")


AXIOMS = [
    SubClassOf(sub=named("PositiveResult"), sup=named("StudyResult")),
    SubClassOf(sub=named("StudyResult"), sup=Some(property=Property(name="produced_by"),
                                                  filler=named("Study"))),
    Domain(property="rests_on", domain=named("EvidenceLine")),
    Range(property="rests_on", range=named("StudyResult")),
    SubPropertyOf(sub=(Property(name="supports"),), sup=Property(name="bears_on")),
    InverseProperties(first="part_of", second="has_part"),
    DisjointClasses(classes=(named("StudyResult"), named("Study"))),
]


def answers(text: str, nodes, links) -> set[tuple[str, ...]]:  # noqa: ANN001
    return {one.values for one in evaluate(rewrite(parse(text), tbox(AXIOMS)), nodes, links)}


def test_a_sub_class_and_a_range_answer_for_the_class_above_them() -> None:
    nodes = [node("pos", "PositiveResult"), node("line", "EvidenceLine"), node("r2", "Result")]
    links = [link("l", "rests_on", "line", "r2")]
    assert answers("q(?x) :- StudyResult(?x)", nodes, links) == {("pos",), ("r2",)}


def test_an_existential_answers_where_its_other_end_is_not_asked_for() -> None:
    """Every result was produced by some study, recorded or not."""
    nodes = [node("pos", "PositiveResult")]
    assert answers("q(?x) :- produced_by(?x, ?s)", nodes, []) == {("pos",)}
    # Asked for the study itself, there is no row to name: nothing is invented.
    assert answers("q(?x, ?s) :- produced_by(?x, ?s)", nodes, []) == set()


def test_a_sub_relation_and_an_inverse_are_asked_for_too() -> None:
    links = [link("s", "supports", "line", "p"), link("h", "has_part", "whole", "piece")]
    assert answers("q(?l, ?p) :- bears_on(?l, ?p)", [], links) == {("line", "p")}
    assert answers("q(?x, ?y) :- part_of(?x, ?y)", [], links) == {("piece", "whole")}


def test_a_negative_inclusion_is_a_query_for_what_breaks_it() -> None:
    t = tbox(AXIOMS)
    [(query, axiom)] = [one for one in violations(t) if "DisjointClasses" in one[1]]
    nodes = [node("x", "PositiveResult")]
    links = [link("p", "produced_by", "y", "x")]
    assert not evaluate(rewrite(query, t), nodes, links)
    both = [node("x", "Study"), node("y", "PositiveResult")]
    assert not evaluate(rewrite(query, t), both, [])
    same = [node("x", "Study"), *[node("x", "StudyResult")]]
    assert evaluate(rewrite(query, t), same, [])


def test_what_qL_cannot_rewrite_with_is_left_out() -> None:
    from atlas.model.owl import HasCharacteristic

    transitive = HasCharacteristic(property="part_of", characteristic="transitive")
    assert tbox([transitive]).ignored == [transitive]


def test_a_query_that_is_not_one_is_refused_with_how_to_write_it() -> None:
    with pytest.raises(ValueError, match="q\\(\\?x\\)"):
        parse("give me the results")
    with pytest.raises(ValueError, match="\\?y"):
        parse("q(?y) :- Result(?x)")


def test_the_sql_a_rewriting_compiles_to_returns_what_evaluation_does(tmp_path) -> None:  # noqa: ANN001
    from atlas.model import Agent, Assertion

    store = SqliteStore(tmp_path / "store.db")
    store.add_source(SOURCE)
    rows = [node("pos", "PositiveResult"), node("line", "EvidenceLine"), node("r2", "Result"),
            link("l", "rests_on", "line", "r2")]
    for index, target in enumerate(rows):
        store.assert_(Assertion(id=f"a{index}", agent=Agent(id="run", kind="run"),
                                at="2026-01-01T00:00:00+00:00", target=target))
    ucq = rewrite(parse("q(?x) :- StudyResult(?x)"), tbox(AXIOMS))
    in_sql = set()
    for query in ucq:
        sql, params = to_sql(query)
        in_sql |= {tuple(row[:1]) for row in store.select(sql, params)}
    in_memory = {one.values for one in evaluate(ucq, store.nodes(), store.links())}
    assert in_sql == in_memory == {("pos",), ("r2",)}


def test_the_shipped_ql_ontology_rewrites_a_question_about_bearing_on_a_claim() -> None:
    schema = load("science_core_ql")
    ucq = rewrite(parse("q(?l, ?p) :- bears_on(?l, ?p)"), tbox(schema.every_axiom()))
    assert {one.atoms[0].predicate for one in ucq} == {"bears_on", "supports", "disputes"}
