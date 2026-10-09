"""Answering a conjunctive query by rewriting it with the ontology, and packaging the answers.

The OWL 2 QL engine (`atlas/reason/ql.py`) turns a query over the ontology's vocabulary --

    q(?r, ?p) :- StudyResult(?r), rests_on(?line, ?r), bears_on(?line, ?p)

-- into a union of queries over what is literally stored, and the union's answers are the
certain answers: everything the ontology and the data together imply, and nothing any row
had to be invented for. A store that can run SQL (`SqliteStore.select`) runs each query in
the union as a join; any other store is evaluated in memory. Either way, the ontology did
its work before the store was touched, which is what ontology-based data access means.

The answers are then a package like any other. The nodes they name are the roots, the rows
that witnessed them are recorded in the package's reasons, and `expand` walks out from them
with the same guarantees as every other selection -- the objection pulled in, the partial
package said to be partial -- so a QL architecture is answered from a walked graph, not
from a table of rows.

`consistency` also asks the store for what breaks each negative inclusion -- two disjoint
classes on one node, two disjoint relations on one pair -- and reports it, without changing
what is answered: an inconsistency is a finding about the data, not a reason to refuse a
question over it.
"""

from __future__ import annotations

from pydantic import Field

from atlas.model import Frozen, Schema
from atlas.reason.ql import Answer, Query, evaluate, parse, rewrite, tbox, to_sql, violations
from atlas.steps import State, register
from atlas.steps.graph_expand import GraphExpandOptions, expand


class QueryOptions(Frozen):
    """The query, whether to push it into SQL, and how the answers are walked."""

    query: str = Field(min_length=1, description="q(?x, ...) :- Class(?x), relation(?x, ?y)")
    sql: bool = Field(True, description="Run each rewritten query in the store where it can")
    consistency: bool = Field(False, description="Also report what breaks a negative inclusion")
    limit: int = Field(200, gt=0, description="Answers carried into the package")
    expand: GraphExpandOptions = GraphExpandOptions()


class Inconsistency(Frozen):
    axiom: str
    rows: tuple[tuple[str, ...], ...]


@register("query", requires=("store", "schema"),
          produces=("answers", "rewriting", "bundle", "inconsistencies"), options=QueryOptions)
def query(state: State, options: QueryOptions) -> State:
    """Rewrite the query, answer it over the store, and package what it found."""
    schema: Schema = state["schema"]
    store = state["store"]
    t = tbox(schema.every_axiom())
    asked = _check(parse(options.query), schema)
    union = rewrite(asked, t)
    found = answer(union, store, sql=options.sql)[: options.limit]
    held = {node.id for node in store.nodes()}
    roots = tuple(dict.fromkeys(value for one in found for value in one.values if value in held))
    bundle = expand(
        store, roots, options.expand,
        reasons={root: f"an answer to {asked.text()}" for root in roots},
        snapshot=schema.version, method="query",
    )
    inconsistent: tuple[Inconsistency, ...] = ()
    if options.consistency:
        inconsistent = tuple(
            Inconsistency(axiom=axiom, rows=tuple(one.values for one in rows))
            for check, axiom in violations(t)
            if (rows := answer(rewrite(check, t), store, sql=options.sql))
        )
    return {"answers": found, "rewriting": tuple(one.text() for one in union), "bundle": bundle,
            "inconsistencies": inconsistent}


def answer(union: tuple[Query, ...], store, *, sql: bool = True) -> tuple[Answer, ...]:  # noqa: ANN001
    """The answers of a union of queries, run as SQL where the store can and in memory if not."""
    select = getattr(store, "select", None) if sql else None
    if select is None:
        return evaluate(union, store.nodes(), store.links())
    found: dict[tuple[str, ...], tuple[str, ...]] = {}
    for one in union:
        statement, params = to_sql(one)
        width = len(one.head)
        for row in select(statement, params):
            found.setdefault(tuple(row[:width]), tuple(row[width:]))
    return tuple(Answer(values=k, witnesses=v) for k, v in sorted(found.items()))


def _check(asked: Query, schema: Schema) -> Query:
    """Refuse a query naming a class or a relation the ontology does not have.

    The same defence as a plan's type check: a query that names an unknown relation would
    be answered with nothing, and nothing looks exactly like "there is no such thing".
    """
    for atom in asked.atoms:
        if len(atom.args) == 1 and schema.find_type(atom.predicate) is None:
            raise ValueError(f"{atom.text()}: no class {atom.predicate!r} in this ontology")
        if len(atom.args) == 2 and schema.find_predicate(atom.predicate) is None:
            raise ValueError(f"{atom.text()}: no relation {atom.predicate!r} in this ontology")
    return asked


__all__ = ["Inconsistency", "QueryOptions", "answer", "query"]
