"""Answering a compound question as a plan of typed graph operations, each of which is checked.

*"Which methods improved the result under the same protocol, were reproduced
independently, and have no strong refutation?"* is not one retrieval. It is a
composition: resolve some things, traverse to what was found about them, filter to the
comparable ones, count the independent confirmations, and bring in what argues the other
way. Every other architecture here answers such a question by retrieving a
neighbourhood and hoping the model composes correctly inside the prose. This one makes
the composition explicit, executes it step by step, and keeps the witnesses of each step.

Three things make that worth doing, and each is a rule the interpreter enforces.

**A plan is type-checked before it runs.** Every operator's arguments are checked against
the loaded ontology: a predicate the ontology does not declare, a type it does not know, an
operator nobody implements. That is what stops a planner -- a person or a model -- from
replacing an unknown relation with a similar-looking word and getting a plausible answer
built on a relation nobody asserted. The check happens once, before anything executes,
so the failure names the whole plan rather than the step that happened to run first.

**An operator with no data says so, and the plan continues.** `resolve` that matched
nothing hands the next operator an empty set with a reason attached, and the reason
travels to the end. A plan that raised would tell you it failed; a plan that carried on
silently would tell you the answer is empty. Neither says *which step emptied it*, which
is the only useful thing.

**An aggregate counts the whole selected set.** Not the top few, not what fitted in a
budget. A question of the form "how many" is a question about a set, and answering it
from a ranked sample is answering a different question. Where a budget did bind, the
trace says so and the count is marked partial.

**The ontology rewrites each operator, as OWL 2 QL does.** `resolve` of a class is asked as
the query `C(?x)` and rewritten by the QL engine into the union of queries over what is
stored -- every subclass, every relation whose domain or range makes its subject or object a
C -- and run as SQL where the store can; `traverse` of a relation also crosses every relation
the ontology makes a kind of it, in the direction the ontology says, so `part_of` forward is
also `has_part` backward. Each step records the rewriting it ran in the trace, which is how a
reader sees that an answer came from the ontology's meaning of a word and not only its
spelling. Nothing is materialised: the rewriting returns stored rows, and nothing else.

The operators are read-only. Nothing here writes to a store, and the plan language has no
operator that could.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from itertools import islice
from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Node, Schema
from atlas.model.owl import TOP
from atlas.reason.ql import Atom, Query, TBox, directed, rewrite, tbox
from atlas.steps import State, register
from atlas.steps.graph_expand import GraphExpandOptions, expand
from atlas.steps.query import answer
from atlas.text import normalise, tokenise
from atlas.walk import Adjacency

Name = Literal["resolve", "traverse", "filter", "join", "aggregate", "compare", "oppose"]
"""The operators a plan may use. Small on purpose: each one is a graph operation whose
result can be shown, and a language with an escape hatch would have no type check."""


class Operator(Frozen):
    """One step of a plan: what to do, and what to do it with."""

    op: Name
    predicate: str = ""
    type: str = ""
    field: str = ""
    value: str = ""
    terms: tuple[str, ...] = ()
    forward: bool = True

    def describe(self) -> str:
        """The operator as a reader sees it in the trace."""
        parts = [
            f"{key}={value!r}"
            for key, value in (("predicate", self.predicate), ("type", self.type),
                               ("field", self.field), ("value", self.value))
            if value
        ]
        if self.terms:
            parts.append(f"terms={list(self.terms)}")
        return f"{self.op}({', '.join(parts)})"


class Executed(Frozen):
    """What one operator did: what it produced, what it stood on, and why it produced nothing."""

    operator: Operator
    nodes: tuple[str, ...] = ()
    witnesses: tuple[str, ...] = Field(default=(), description="Links the step crossed")
    count: int | None = None
    groups: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    rewriting: tuple[str, ...] = Field(
        default=(), description="What the ontology rewrote the operator into, as queries"
    )
    reason: str = ""
    inputs: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.nodes)


class Trace(Frozen):
    """The whole execution: every step, in order, with what it produced."""

    steps: tuple[Executed, ...] = ()
    partial: bool = False

    @property
    def emptied_at(self) -> Executed | None:
        """The first step that produced nothing, which is what a reader needs to know."""
        return next((step for step in self.steps if not step.nodes and step.count is None), None)

    def __len__(self) -> int:
        return len(self.steps)


class PlanOptions(Frozen):
    """The plan, and what it may spend.

    The plan is written in the configuration. A planner that produces one -- a person, a
    model -- substitutes for that, and the type check below is what makes accepting a
    generated plan safe rather than hopeful.
    """

    plan: tuple[Operator, ...] = ()
    limit: int = Field(500, gt=0, description="Nodes an operator may carry forward")
    sql: bool = Field(True, description="Run a rewritten resolve in the store where it can")
    expand: GraphExpandOptions = GraphExpandOptions()
    strict: bool = False
    max_steps: int = Field(16, gt=0, le=128)
    max_graph_nodes: int = Field(100000, gt=0)
    max_graph_links: int = Field(200000, gt=0)


class PlanRefused(ValueError):
    """A strict plan cannot be executed under its declared contracts."""

    def __init__(self, category: Literal["schema", "operator", "budget"], reason: str) -> None:
        self.category = category
        super().__init__(reason)


@register("execute_plan", requires=("store", "schema"),
          produces=("bundle", "trace", "answer_count"), options=PlanOptions)
def execute_plan(state: State, options: PlanOptions) -> State:
    """Check the plan against the ontology, run it, and package what the last step selected."""
    store = state["store"]
    schema: Schema = state["schema"]
    if options.strict:
        _strict_checked(options, schema)
    problems = check(options.plan, schema)
    if problems:
        raise ValueError(f"the plan does not type-check: {'; '.join(problems)}")
    trace = run(store, schema, options, seeds=state.get("hits", ()))
    selected = trace.steps[-1].nodes if trace.steps else ()
    adjacency = Adjacency.of(store.links(), options.expand.follow)
    bundle = expand(
        store,
        selected,
        options.expand,
        reasons={
            node_id: f"selected by {trace.steps[-1].operator.describe()}"
            for node_id in selected
        },
        snapshot=schema.version,
        method="execute_plan",
        adjacency=adjacency,
        schema=schema,
    )
    counted = next((step.count for step in reversed(trace.steps) if step.count is not None), None)
    return {"bundle": bundle, "trace": trace, "answer_count": counted}


def check(plan: Sequence[Operator], schema: Schema) -> list[str]:
    """Everything wrong with a plan, before any of it runs.

    A predicate the ontology does not declare and a type it does not know are both refused
    here, which is the whole defence against a planner replacing an unknown relation
    with a plausible-looking word: the plan names relations of the ontology or it does not
    run at all.
    """
    problems: list[str] = []
    for index, operator in enumerate(plan):
        where = f"step {index + 1}, {operator.describe()}"
        if operator.predicate and schema.find_predicate(operator.predicate) is None:
            problems.append(f"{where}: no relation {operator.predicate!r} in this ontology")
        if operator.type and schema.find_type(operator.type) is None:
            problems.append(f"{where}: no class {operator.type!r} in this ontology")
        if operator.op in ("traverse", "join", "oppose") and not operator.predicate:
            problems.append(f"{where}: needs a relation to cross")
        if operator.op == "filter" and not operator.field:
            problems.append(f"{where}: needs a field to filter on")
    return problems


def run(store, schema: Schema, options: PlanOptions, seeds: Iterable = ()) -> Trace:
    """Execute a checked plan, carrying a set of nodes from one operator to the next."""
    plan = options.plan
    if options.strict:
        _strict_checked(options, schema)
        plan = tuple(_canonical(operator, schema) for operator in plan)
        nodes = tuple(islice(iter(store.nodes()), options.max_graph_nodes + 1))
        if len(nodes) > options.max_graph_nodes:
            raise PlanRefused("budget", "the graph exceeds the node budget")
        links = tuple(islice(iter(store.links()), options.max_graph_links + 1))
        if len(links) > options.max_graph_links:
            raise PlanRefused("budget", "the graph exceeds the link budget")
    else:
        nodes, links = store.nodes(), store.links()
    held = {node.id: node for node in nodes}
    adjacency = Adjacency.of(links)
    t = tbox(schema.every_axiom())
    carried: tuple[str, ...] = tuple(hit.node.id for hit in seeds)
    steps: list[Executed] = []
    partial = False
    for operator in plan:
        step = _apply(operator, carried, held, adjacency, schema,
                      _Access(store, t, options.sql, strict=options.strict, limit=options.limit))
        step = step.model_copy(update={
            "inputs": carried,
            "excluded": tuple(node_id for node_id in carried if node_id not in step.nodes)
            if operator.op == "filter" or (options.strict and operator.op == "join") else (),
        })
        if len(step.nodes) > options.limit:
            if options.strict:
                raise PlanRefused("budget", f"{operator.describe()} exceeds the node budget")
            # A budget that bound is not a smaller answer: it is the same answer with a
            # warning on it, and the count above it is marked partial for the same reason.
            step = step.model_copy(update={"nodes": step.nodes[:options.limit],
                                           "reason": "more than the budget allows"})
            partial = True
        steps.append(step)
        carried = step.nodes
    return Trace(steps=tuple(steps), partial=partial)


def _canonical(operator: Operator, schema: Schema) -> Operator:
    """Use vocabulary names after checking identities, including CURIE arguments."""
    type_def = schema.find_type(operator.type) if operator.type else None
    predicate = schema.find_predicate(operator.predicate) if operator.predicate else None
    return operator.model_copy(update={
        "type": type_def.name if type_def else operator.type,
        "predicate": predicate.name if predicate else operator.predicate,
    })


def _strict_checked(options: PlanOptions, schema: Schema) -> None:
    if len(options.plan) > options.max_steps:
        raise PlanRefused("budget", "the plan exceeds the operator budget")
    problems = check_strict(options.plan, schema)
    if problems:
        raise PlanRefused("schema", "; ".join(problems))
    opposing = {predicate.name for name in options.expand.opposes
                if (predicate := schema.find_predicate(name)) is not None}
    if any(operator.op == "oppose" and _canonical(operator, schema).predicate not in opposing
           for operator in options.plan):
        raise PlanRefused("operator", "opposition needs a predicate declared by expand.opposes")


def check_strict(plan: Sequence[Operator], schema: Schema) -> list[str]:
    """Check a closed operator language and its possible class flow without reading data.

    Strict plans start from a declared class, never from retrieval's sampled seeds.
    Field operations require a field on every possible carried class. A class filter
    can narrow that set first. A join preserves anchors and checks the matched side;
    opposition admits both endpoints and preserves the complete opposing component.
    """
    problems = check(plan, schema)
    if not plan or plan[0].op != "resolve":
        problems.append("a strict plan must start with resolve")
    possible: set[str] = set()
    allowed = {
        "resolve": {"type", "terms"},
        "traverse": {"predicate", "forward"},
        "filter": {"type", "field", "value"},
        "aggregate": set(),
        "compare": {"field"},
        "join": {"predicate", "forward", "type", "field", "value"},
        "oppose": {"predicate"},
    }
    for index, raw in enumerate(plan):
        operator = _canonical(raw, schema)
        where = f"step {index + 1}, {operator.describe()}"
        if operator.op not in allowed:
            problems.append(f"{where}: no strict contract for this operator")
            continue
        defaults = Operator(op=operator.op)
        for name in ("type", "predicate", "field", "value", "terms", "forward"):
            if name not in allowed[operator.op] and getattr(raw, name) != getattr(defaults, name):
                problems.append(f"{where}: unused argument {name!r}")
        if operator.op == "resolve":
            if not operator.type:
                problems.append(f"{where}: needs a declared class")
            possible = {one.name for one in schema.types if schema.is_a(one.name, operator.type)}
        elif operator.op in ("traverse", "join", "oppose"):
            predicate = schema.find_predicate(operator.predicate)
            if predicate is None:
                possible = set()
                continue
            missing = [name for name in (predicate.domain, predicate.range)
                       if name != TOP and schema.find_type(name) is None]
            if missing:
                problems.append(f"{where}: relation endpoints are not declared: {missing!r}")
                possible = set()
                continue
            domain, range_ = (predicate.domain, predicate.range) if operator.forward else (
                predicate.range, predicate.domain
            )
            if operator.op == "oppose":
                wrong = sorted(name for name in possible if domain != TOP and range_ != TOP
                               and not schema.is_a(name, domain) and not schema.is_a(name, range_))
                if wrong:
                    problems.append(f"{where}: relation endpoints do not admit {wrong!r}")
                possible |= {one.name for one in schema.types if domain == TOP or range_ == TOP
                             or schema.is_a(one.name, domain) or schema.is_a(one.name, range_)}
                continue
            if domain != TOP:
                wrong = sorted(name for name in possible if not schema.is_a(name, domain))
                if wrong:
                    problems.append(f"{where}: relation endpoint does not admit {wrong!r}")
            matched = {one.name for one in schema.types
                       if range_ == TOP or schema.is_a(one.name, range_)}
            if operator.op == "join":
                narrowed = {name for name in matched if not operator.type
                            or schema.is_a(name, operator.type)}
                if matched and not narrowed:
                    problems.append(f"{where}: matched class is incompatible with the endpoint")
                if operator.value and not operator.field:
                    problems.append(f"{where}: a matched value needs a field")
                wrong = sorted(name for name in narrowed if operator.field
                    and operator.field not in {
                        field.name for field in schema.declared_fields(name)})
                if wrong:
                    problems.append(f"{where}: matched field {operator.field!r} "
                                    f"is not declared on {wrong!r}")
            else:
                possible = matched
        elif operator.op in ("filter", "compare"):
            if operator.type:
                narrowed = {name for name in possible if schema.is_a(name, operator.type)}
                if possible and not narrowed:
                    problems.append(f"{where}: class filter is incompatible with the carried set")
                possible = narrowed
            if not operator.field:
                if operator.op == "compare":
                    problems.append(f"{where}: needs a field to compare")
                continue
            wrong = sorted(name for name in possible if operator.field not in {
                field.name for field in schema.declared_fields(name)
            })
            if wrong:
                problems.append(f"{where}: field {operator.field!r} is not declared on {wrong!r}")
    return problems


class _Access:
    """What an operator needs to ask the ontology and the store: the QL TBox and the store."""

    def __init__(self, store, t: TBox, sql: bool, *, strict: bool, limit: int) -> None:  # noqa: ANN001
        self.store, self.t, self.sql, self.strict, self.limit = store, t, sql, strict, limit


def _apply(
    operator: Operator,
    carried: tuple[str, ...],
    held: dict[str, Node],
    adjacency: Adjacency,
    schema: Schema,
    access: _Access,
) -> Executed:
    """One operator over what the previous one produced."""
    if operator.op == "resolve":
        return _resolve(operator, held, schema, access)
    if not carried:
        return Executed(operator=operator, count=0 if operator.op == "aggregate" else None,
                        reason="nothing reached this step")
    if access.strict and operator.op == "join":
        return _join(operator, carried, held, adjacency, schema, access)
    if access.strict and operator.op == "oppose":
        return _opposition(operator, carried, adjacency, access.t, access.limit)
    if operator.op in ("traverse", "join", "oppose"):
        return _traverse(operator, carried, adjacency, access.t)
    if operator.op == "filter":
        return _filter(operator, carried, held, schema)
    if operator.op == "aggregate":
        return Executed(operator=operator, nodes=carried, count=len(carried))
    return _compare(operator, carried, held)


def _resolve(
    operator: Operator, held: dict[str, Node], schema: Schema, access: _Access
) -> Executed:
    """The nodes a plan names, by class and by the words they use.

    A class is resolved twice over and the answers joined: by the classified hierarchy,
    which holds what the EL engine concluded at load, and by the QL rewriting of `C(?x)`,
    which also finds a node the ontology makes a C by the relations it stands in. Both are
    sound, so their union is.
    """
    asked = {term for word in operator.terms for term in tokenise(word)}
    typed: set[str] = set(held)
    rewriting: tuple[str, ...] = ()
    if operator.type:
        name = schema.find_type(operator.type).name  # type: ignore[union-attr] -- checked
        union = rewrite(Query(head=("?x",), atoms=(Atom(name, ("?x",)),)), access.t)
        rewriting = tuple(one.text() for one in union)
        certain = {one.values[0] for one in answer(union, access.store, sql=access.sql)}
        typed = {node_id for node_id, node in held.items()
                 if schema.is_a(node.type, operator.type) or node_id in certain}
    found = tuple(sorted(
        node_id for node_id in typed
        if not asked or asked & set(tokenise(held[node_id].text()))
    ))
    reason = "" if found else "no node of this ontology matches those terms"
    return Executed(operator=operator, nodes=found, rewriting=rewriting, reason=reason)


def _traverse(
    operator: Operator, carried: tuple[str, ...], adjacency: Adjacency, t: TBox
) -> Executed:
    """Where one relation leads from everything carried, keeping the links it crossed.

    The relation is the rewriting of `r(?x, ?y)`: every relation the ontology makes a kind of
    it, each crossed the way round the ontology says -- an inverse is crossed backwards.
    """
    ways = directed(t, operator.predicate)
    reached: list[str] = []
    crossed: list[str] = []
    for node_id in carried:
        for edge in adjacency.edges(node_id):
            if (edge.predicate, edge.forward != operator.forward) not in ways:
                continue
            crossed.append(edge.link_id)
            if edge.other not in reached:
                reached.append(edge.other)
    reason = "" if reached else f"nothing carried is related by {operator.predicate!r}"
    return Executed(
        operator=operator, nodes=tuple(reached), witnesses=tuple(sorted(set(crossed))),
        rewriting=tuple(f"{name}(?y, ?x)" if back else f"{name}(?x, ?y)" for name, back in ways),
        reason=reason,
    )


def _join(
    operator: Operator, carried: tuple[str, ...], held: dict[str, Node],
    adjacency: Adjacency, schema: Schema, access: _Access,
) -> Executed:
    """A relation semijoin: preserve anchors with matches and retain every matched pair.

    Groups map each surviving anchor to its matched objects. Aggregates count anchors,
    once each; pair multiplicity is visible in groups and never duplicates an anchor.
    """
    predicate = schema.find_predicate(operator.predicate)
    target_type = predicate.range if operator.forward else predicate.domain
    target_type = operator.type or ("" if target_type == TOP else target_type)
    resolved = _resolve(Operator(op="resolve", type=target_type), held, schema, access)
    wanted = normalise(operator.value)
    eligible = {node_id for node_id in resolved.nodes if not operator.field
                or _matches(held[node_id], operator.field, wanted)}
    ways = directed(access.t, operator.predicate)
    groups: dict[str, tuple[str, ...]] = {}
    crossed: set[str] = set()
    for anchor in carried:
        matches: set[str] = set()
        for edge in adjacency.edges(anchor):
            if ((edge.predicate, edge.forward != operator.forward) in ways
                    and edge.other in eligible):
                matches.add(edge.other)
                crossed.add(edge.link_id)
        if matches:
            groups[anchor] = tuple(sorted(matches))
    return Executed(operator=operator, nodes=tuple(groups), groups=groups,
        witnesses=tuple(sorted(crossed)), rewriting=(*resolved.rewriting, *(
            f"{name}(?y, ?x)" if back else f"{name}(?x, ?y)" for name, back in ways)),
        reason="" if groups else "no anchor has a matching object across the declared relation")


def _opposition(
    operator: Operator, carried: tuple[str, ...], adjacency: Adjacency, t: TBox, limit: int,
) -> Executed:
    """Both sides of the complete opposition component; this walk asserts no symmetry."""
    predicates = {name for name, _ in directed(t, operator.predicate)}
    reached = set(carried)
    pending = deque(carried)
    crossed: set[str] = set()
    while pending:
        for edge in adjacency.edges(pending.popleft()):
            if edge.predicate not in predicates:
                continue
            crossed.add(edge.link_id)
            if edge.other not in reached:
                reached.add(edge.other)
                if len(reached) > limit:
                    raise PlanRefused("budget", "opposition closure exceeds the node budget")
                pending.append(edge.other)
    return Executed(operator=operator, nodes=tuple(sorted(reached)),
        witnesses=tuple(sorted(crossed)),
        rewriting=tuple(f"walk both endpoints of {name}" for name in sorted(predicates)),
        reason="" if crossed else "no declared opposition links are reachable from the anchors")


def _filter(
    operator: Operator, carried: tuple[str, ...], held: dict[str, Node], schema: Schema
) -> Executed:
    """What carried survives a condition on a field, or on a type."""
    wanted = normalise(operator.value)
    kept = tuple(
        node_id for node_id in carried
        if node_id in held
        and (not operator.type or schema.is_a(held[node_id].type, operator.type))
        and _matches(held[node_id], operator.field, wanted)
    )
    reason = "" if kept else f"nothing carried has {operator.field!r} matching {operator.value!r}"
    return Executed(operator=operator, nodes=kept, reason=reason)


def _compare(operator: Operator, carried: tuple[str, ...], held: dict[str, Node]) -> Executed:
    """Carried things grouped by what a field says, so like is put beside like."""
    groups: dict[str, list[str]] = {}
    for node_id in carried:
        node = held.get(node_id)
        if node is None:
            continue
        groups.setdefault(normalise(node.fields.get(operator.field, "")) or "unrecorded",
                          []).append(node_id)
    return Executed(
        operator=operator,
        nodes=carried,
        groups={key: tuple(value) for key, value in sorted(groups.items())},
        reason="" if len(groups) > 1 else "everything carried falls in one group",
    )


def _matches(node: Node, field: str, wanted: str) -> bool:
    """Whether a node's field satisfies the condition; an empty value means "has one"."""
    value = normalise(node.fields.get(field, ""))
    return bool(value) if not wanted else value == wanted
