"""OWL 2 QL: answering a query over what is stored by rewriting it, never by materialising.

QL is the profile of ontology-based data access. A conjunctive query -- "the results
produced by a study, and the propositions some line of argument bears on" -- is rewritten
with the ontology's axioms into a union of conjunctive queries, each of which mentions only
what is literally stored: node types as asserted, relations as asserted. Evaluating that
union over the store gives the **certain answers**, everything the ontology and the data
together imply, and nothing is ever written or invented to get them. That is what lets a
relational store answer an ontological question with joins, and it is why the relational
and the mapped-table architectures run this engine and not the RL one.

The algorithm is PerfectRef (Calvanese, De Giacomo, Lembo, Lenzerini and Rosati, "Tractable
reasoning and efficient query answering in description logics: the DL-Lite family", JAR
2007): repeatedly replace an atom by what a positive inclusion says implies it, and unify
two atoms where that makes a variable unbound, until no new query appears. It terminates
because a QL ontology has no transitive relation and no chain -- the reason those are not
in the profile.

Negative inclusions -- disjoint classes, disjoint relations, asymmetry -- are not used to
rewrite. They are checked: each becomes a query for its violation, rewritten and asked
like any other, and a non-empty answer is a clash with the rows that witness it.

A query is written the way a person reads it:

    q(?r, ?p) :- StudyResult(?r), bears_on(?line, ?p), rests_on(?line, ?r)

A term starting with `?` is a variable, anything else is a node id.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from atlas.model.owl import (
    TOP,
    And,
    Axiom,
    ClassExpression,
    DisjointClasses,
    DisjointProperties,
    Domain,
    EquivalentClasses,
    EquivalentProperties,
    HasCharacteristic,
    InverseProperties,
    Named,
    Not,
    Range,
    Some,
    SubClassOf,
    SubPropertyOf,
)

Role = tuple[str, bool]
Basic = tuple  # ("class", name) | ("exists", role)
FRESH = "_ql:"
MAX_QUERIES = 5000


@dataclass(frozen=True, order=True)
class Atom:
    """A class atom has one argument, a relation atom two."""

    predicate: str
    args: tuple[str, ...]

    def text(self) -> str:
        return f"{self.predicate}({', '.join(self.args)})"


@dataclass(frozen=True)
class Query:
    head: tuple[str, ...]
    atoms: tuple[Atom, ...]

    def text(self) -> str:
        return f"q({', '.join(self.head)}) :- {', '.join(one.text() for one in self.atoms)}"

    def variables(self) -> set[str]:
        return {term for atom in self.atoms for term in atom.args if is_variable(term)}


@dataclass
class TBox:
    """The positive and negative inclusions of a QL ontology."""

    concept: list[tuple[Basic, Basic]] = field(default_factory=list)     # B1 ⊑ B2
    role: list[tuple[Role, Role]] = field(default_factory=list)          # R1 ⊑ R2
    negative: list[tuple[Basic, Basic, str]] = field(default_factory=list)
    negative_roles: list[tuple[Role, Role, str]] = field(default_factory=list)
    classes: set[str] = field(default_factory=set)
    ignored: list[Axiom] = field(default_factory=list)
    _count: int = 0

    def fresh(self) -> str:
        self._count += 1
        return f"{FRESH}{self._count}"


@dataclass(frozen=True)
class Answer:
    """One tuple of certain answers, with the stored rows that witness it."""

    values: tuple[str, ...]
    witnesses: tuple[str, ...]


def is_variable(term: str) -> bool:
    return term.startswith("?")


def parse(text: str) -> Query:
    """A query from its written form; `ValueError` naming what could not be read."""
    match = re.fullmatch(r"\s*(\w+)\s*\(([^)]*)\)\s*:-\s*(.+?)\s*\.?\s*", text, re.S)
    if match is None:
        raise ValueError(f"not a query: {text!r}; write q(?x) :- Type(?x), relation(?x, ?y)")
    head = tuple(one.strip() for one in match.group(2).split(",") if one.strip())
    atoms = tuple(
        Atom(predicate=name, args=tuple(one.strip() for one in args.split(",")))
        for name, args in re.findall(r"([\w:.\-]+)\s*\(([^)]*)\)", match.group(3))
    )
    if not atoms:
        raise ValueError(f"a query needs at least one atom: {text!r}")
    for atom in atoms:
        if len(atom.args) not in (1, 2):
            raise ValueError(f"{atom.text()}: an atom takes one argument or two")
    missing = [one for one in head if one not in {t for a in atoms for t in a.args}]
    if missing:
        raise ValueError(f"the answer names {', '.join(missing)}, which no atom mentions")
    return Query(head=head, atoms=atoms)


# ---- the ontology, as inclusions ----------------------------------------------------------


def tbox(axioms: Iterable[Axiom]) -> TBox:
    """The inclusions of the ontology that QL can rewrite with, and what it cannot use."""
    t = TBox()
    for axiom in axioms:
        if not _take(axiom, t):
            t.ignored.append(axiom)
    return t


def _basic(expression: ClassExpression) -> Basic | None:
    if isinstance(expression, Named) and expression.name != TOP:
        return ("class", expression.name)
    if isinstance(expression, Some) and isinstance(expression.filler, Named) and (
        expression.filler.name == TOP
    ):
        return ("exists", (expression.property.name, expression.property.inverse))
    return None


def _right(t: TBox, left: Basic, expression: ClassExpression, text: str) -> bool:
    """Add left ⊑ expression, for any expression QL allows on the right."""
    if isinstance(expression, And):
        return all([_right(t, left, one, text) for one in expression.operands])
    if isinstance(expression, Not):
        other = _basic(expression.operand)
        if other is None:
            return False
        t.negative.append((left, other, text))
        return True
    if isinstance(expression, Some) and isinstance(expression.filler, Named) and (
        expression.filler.name != TOP
    ):
        # B ⊑ ∃R.A is B ⊑ ∃R', R' ⊑ R, ∃R'⁻ ⊑ A, for a role R' that nothing else mentions.
        role = (expression.property.name, expression.property.inverse)
        fresh = (t.fresh(), False)
        t.role.append((fresh, role))
        t.concept.append((left, ("exists", fresh)))
        t.concept.append((("exists", (fresh[0], True)), ("class", expression.filler.name)))
        return True
    right = _basic(expression)
    if right is None:
        return False
    t.concept.append((left, right))
    return True


def _take(axiom: Axiom, t: TBox) -> bool:
    text = axiom.text()
    if isinstance(axiom, SubClassOf):
        left = _basic(axiom.sub)
        return left is not None and _right(t, left, axiom.sup, text)
    if isinstance(axiom, EquivalentClasses):
        members = [_basic(one) for one in axiom.classes]
        if any(one is None for one in members):
            return False
        for first, second in itertools.permutations(members, 2):
            t.concept.append((first, second))
        return True
    if isinstance(axiom, DisjointClasses):
        members = [_basic(one) for one in axiom.classes]
        if any(one is None for one in members):
            return False
        for first, second in itertools.combinations(members, 2):
            t.negative.append((first, second, text))
        return True
    if isinstance(axiom, Domain):
        return _right(t, ("exists", (axiom.property, False)), axiom.domain, text)
    if isinstance(axiom, Range):
        return _right(t, ("exists", (axiom.property, True)), axiom.range, text)
    if isinstance(axiom, SubPropertyOf):
        if axiom.chain:
            return False
        sub, sup = axiom.sub[0], axiom.sup
        t.role.append(((sub.name, sub.inverse), (sup.name, sup.inverse)))
        return True
    if isinstance(axiom, EquivalentProperties):
        roles = [(one.name, one.inverse) for one in axiom.properties]
        for first, second in itertools.permutations(roles, 2):
            t.role.append((first, second))
        return True
    if isinstance(axiom, InverseProperties):
        t.role += [((axiom.first, False), (axiom.second, True)),
                   ((axiom.second, False), (axiom.first, True))]
        return True
    if isinstance(axiom, DisjointProperties):
        roles = [(one.name, one.inverse) for one in axiom.properties]
        for first, second in itertools.combinations(roles, 2):
            t.negative_roles.append((first, second, text))
        return True
    if isinstance(axiom, HasCharacteristic):
        role = (axiom.property, False)
        if axiom.characteristic == "symmetric":
            t.role.append((role, (axiom.property, True)))
            return True
        if axiom.characteristic == "asymmetric":
            t.negative_roles.append((role, (axiom.property, True), text))
            return True
        return axiom.characteristic in ("reflexive", "irreflexive")
    return False


# ---- PerfectRef ---------------------------------------------------------------------------


def rewrite(query: Query, t: TBox, limit: int = MAX_QUERIES) -> tuple[Query, ...]:
    """Every query whose stored answers, together, are the certain answers to this one.

    Each rewriting is kept in a canonical form, so two that differ only in the names of
    their variables are one. Queries mentioning a role this module invented are dropped at
    the end: nothing is stored under such a role, so they can only ever answer nothing.
    """
    seen = {_canonical(query): query}
    frontier = [query]
    while frontier:
        current = frontier.pop()
        for produced in _steps(current, t):
            key = _canonical(produced)
            if key not in seen:
                seen[key] = produced
                frontier.append(produced)
                if len(seen) > limit:
                    raise ValueError(f"the rewriting grew past {limit} queries")
    return tuple(sorted(
        (one for one in seen.values()
         if not any(atom.predicate.startswith(FRESH) for atom in one.atoms)),
        key=lambda one: one.text(),
    ))


def _steps(query: Query, t: TBox) -> Iterable[Query]:
    for index, atom in enumerate(query.atoms):
        for replacement in _replacements(atom, query, t):
            atoms = list(query.atoms)
            atoms[index] = replacement
            yield Query(head=query.head, atoms=tuple(dict.fromkeys(atoms)))
    for first, second in itertools.combinations(range(len(query.atoms)), 2):
        unifier = _unify(query.atoms[first], query.atoms[second])
        if unifier is not None:
            yield _substitute(query, unifier)


def _bound(term: str, query: Query) -> bool:
    """Whether a term matters beyond the atom it is in: a constant, an answer, or a join."""
    if not is_variable(term) or term in query.head:
        return True
    return sum(atom.args.count(term) for atom in query.atoms) > 1


def _replacements(atom: Atom, query: Query, t: TBox) -> Iterable[Atom]:
    """Every atom a positive inclusion says implies this one."""
    if len(atom.args) == 1:
        (x,) = atom.args
        for left, right in t.concept:
            if right == ("class", atom.predicate):
                yield _atom_for(left, x, query)
        return
    x, y = atom.args
    for left, right in t.concept:
        if right[0] != "exists":
            continue
        name, inverse = right[1]
        if name != atom.predicate:
            continue
        # B ⊑ ∃R applies to R(x, _): the second place must not matter.
        if not inverse and not _bound(y, query):
            yield _atom_for(left, x, query)
        if inverse and not _bound(x, query):
            yield _atom_for(left, y, query)
    for sub, sup in t.role:
        # Written so that the super-role is read forwards.
        if sup[1]:
            sub, sup = (sub[0], not sub[1]), (sup[0], False)
        if sup[0] != atom.predicate:
            continue
        yield Atom(sub[0], (y, x) if sub[1] else (x, y))


_counter = itertools.count()


def _atom_for(basic: Basic, term: str, query: Query) -> Atom:
    if basic[0] == "class":
        return Atom(basic[1], (term,))
    name, inverse = basic[1]
    unbound = f"?_{next(_counter)}"
    return Atom(name, (unbound, term) if inverse else (term, unbound))


def _unify(first: Atom, second: Atom) -> dict[str, str] | None:
    if first.predicate != second.predicate or len(first.args) != len(second.args):
        return None
    unifier: dict[str, str] = {}
    for a, b in zip(first.args, second.args, strict=True):
        a, b = unifier.get(a, a), unifier.get(b, b)
        if a == b:
            continue
        if is_variable(a):
            unifier[a] = b
        elif is_variable(b):
            unifier[b] = a
        else:
            return None
    return unifier


def _substitute(query: Query, unifier: Mapping[str, str]) -> Query:
    def term(one: str) -> str:
        while one in unifier:
            one = unifier[one]
        return one

    atoms = tuple(dict.fromkeys(Atom(a.predicate, tuple(term(x) for x in a.args))
                                for a in query.atoms))
    return Query(head=tuple(term(one) for one in query.head), atoms=atoms)


def _canonical(query: Query) -> tuple:
    """A query up to the renaming of its non-answer variables."""
    names: dict[str, str] = {}
    for position, one in enumerate(query.head):
        names.setdefault(one, f"h{position}")
    for atom in sorted(query.atoms, key=lambda a: (a.predicate, len(a.args))):
        for one in atom.args:
            if is_variable(one) and one not in names:
                bound = _bound(one, query)
                names[one] = f"v{len(names)}" if bound else "_"
    return (tuple(names.get(one, one) for one in query.head),
            tuple(sorted((a.predicate, tuple(names.get(x, x) for x in a.args))
                         for a in query.atoms)))


# ---- evaluation ---------------------------------------------------------------------------


def evaluate(queries: Sequence[Query], nodes: Iterable, links: Iterable) -> tuple[Answer, ...]:
    """The answers of a union of queries over nodes and links held in memory.

    Class atoms match a node's asserted type exactly and relation atoms a link's asserted
    predicate exactly: everything else was the rewriting's job, and matching loosely here
    would be reasoning twice.
    """
    by_type: dict[str, list[str]] = {}
    for node in nodes:
        by_type.setdefault(node.type, []).append(node.id)
    by_predicate: dict[str, list] = {}
    for link in links:
        by_predicate.setdefault(link.predicate, []).append(link)
    found: dict[tuple[str, ...], tuple[str, ...]] = {}
    for query in queries:
        for binding, witnesses in _match(list(query.atoms), {}, (), by_type, by_predicate):
            values = tuple(binding.get(one, one) for one in query.head)
            found.setdefault(values, witnesses)
    return tuple(Answer(values=k, witnesses=v) for k, v in sorted(found.items()))


def _match(atoms: list[Atom], binding: dict[str, str], witnesses: tuple[str, ...],
           by_type: Mapping, by_predicate: Mapping) -> Iterable[tuple[dict, tuple]]:
    if not atoms:
        yield binding, witnesses
        return
    atom, rest = atoms[0], atoms[1:]
    if len(atom.args) == 1:
        (x,) = atom.args
        for node_id in by_type.get(atom.predicate, ()):
            extended = _bind(binding, x, node_id)
            if extended is not None:
                yield from _match(rest, extended, (*witnesses, node_id), by_type, by_predicate)
        return
    x, y = atom.args
    for link in by_predicate.get(atom.predicate, ()):
        extended = _bind(binding, x, link.src)
        if extended is not None:
            extended = _bind(extended, y, link.dst)
        if extended is not None:
            yield from _match(rest, extended, (*witnesses, link.id), by_type, by_predicate)


def _bind(binding: dict[str, str], term: str, value: str) -> dict[str, str] | None:
    if not is_variable(term):
        return binding if term == value else None
    if term in binding:
        return binding if binding[term] == value else None
    return {**binding, term: value}


def to_sql(query: Query) -> tuple[str, list[str]]:
    """One conjunctive query as SQL over the `nodes` and `links` tables of the SQLite store.

    Each atom is a table alias, each shared variable a join condition, each constant a
    parameter; the answer columns come first and the ids of the witnessing rows after them.
    """
    tables: list[str] = []
    where: list[str] = []
    params: list[str] = []
    seen: dict[str, str] = {}
    witnesses: list[str] = []
    for index, atom in enumerate(query.atoms):
        alias = f"t{index}"
        if len(atom.args) == 1:
            tables.append(f"nodes {alias}")
            where.append(f"{alias}.type = ?")
            params.append(atom.predicate)
            columns = [f"{alias}.id"]
        else:
            tables.append(f"links {alias}")
            where.append(f"{alias}.predicate = ?")
            params.append(atom.predicate)
            columns = [f"{alias}.src", f"{alias}.dst"]
        witnesses.append(f"{alias}.id")
        for term, column in zip(atom.args, columns, strict=True):
            if not is_variable(term):
                where.append(f"{column} = ?")
                params.append(term)
            elif term in seen:
                where.append(f"{column} = {seen[term]}")
            else:
                seen[term] = column
    # A head term unification turned into a constant is selected as a literal parameter,
    # and those parameters come first because they appear first in the statement.
    head = [seen.get(one, "?") for one in query.head]
    constants = [one for one in query.head if one not in seen]
    select = ", ".join([*head, *witnesses])
    return (f"SELECT DISTINCT {select} FROM {', '.join(tables)} WHERE {' AND '.join(where)}",
            [*constants, *params])


def relations(axioms: Iterable[Axiom], names: Iterable[str]) -> tuple[str, ...]:
    """Every relation a query for these relations is rewritten into, the named ones first.

    The single-atom case of the rewriting: `bears_on(?x, ?y)` is also asked as
    `supports(?x, ?y)` and `disputes(?x, ?y)`, and `part_of(?x, ?y)` as `has_part(?y, ?x)`.
    A walk crosses a link in both directions anyway, so what a walk needs from this is only
    the names -- which is what makes "follow bears_on" follow the support and the dispute,
    and "opposes: [disputes]" pull in every relation the ontology makes a kind of dispute.
    """
    wanted = tuple(dict.fromkeys(names))
    if not wanted:
        return ()
    t = tbox(axioms)
    found = list(wanted)
    for name in wanted:
        for predicate, _ in directed(t, name):
            if predicate not in found:
                found.append(predicate)
    return tuple(found)


def directed(t: TBox, name: str) -> tuple[tuple[str, bool], ...]:
    """The stored relations `name(?x, ?y)` is rewritten into, each with whether it runs backwards.

    `(has_part, True)` in the answer for `part_of` says that `has_part(?y, ?x)` is also an
    answer to `part_of(?x, ?y)`. A step that crosses a relation in one direction needs the
    direction, which `relations` drops.
    """
    found = [(name, False)]
    for one in rewrite(Query(head=("?x", "?y"), atoms=(Atom(name, ("?x", "?y")),)), t):
        if len(one.atoms) != 1 or one.atoms[0].args not in (("?x", "?y"), ("?y", "?x")):
            continue
        key = (one.atoms[0].predicate, one.atoms[0].args == ("?y", "?x"))
        if key not in found:
            found.append(key)
    return tuple(found)


def violations(t: TBox) -> tuple[tuple[Query, str], ...]:
    """A query for each negative inclusion: its answers are what breaks it."""
    found: list[tuple[Query, str]] = []
    for first, second, text in t.negative:
        atoms = (_atom_for(first, "?x", Query((), ())), _atom_for(second, "?x", Query((), ())))
        found.append((Query(head=("?x",), atoms=atoms), text))
    for first, second, text in t.negative_roles:
        atoms = (Atom(first[0], ("?y", "?x") if first[1] else ("?x", "?y")),
                 Atom(second[0], ("?y", "?x") if second[1] else ("?x", "?y")))
        found.append((Query(head=("?x", "?y"), atoms=atoms), text))
    return tuple(found)


__all__ = ["Answer", "Atom", "Query", "TBox", "directed", "evaluate", "is_variable", "parse",
           "relations", "rewrite", "tbox", "to_sql", "violations"]
