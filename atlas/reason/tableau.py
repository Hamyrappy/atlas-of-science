"""OWL 2 DL: deciding whether an ontology can have a model, and which classes can have members.

This is the engine the formal gate runs before an architecture that declares the DL
profile writes anything. It answers two questions about the ontology and none about data:
**is the ontology consistent**, and **is every class satisfiable** -- could anything at all
be an instance of it. A class that cannot is a class the first extractor to produce one
produces an impossible node for, and finding that out after a corpus has been marked up
means marking it up again.

The algorithm is the tableau for SRIQ -- OWL 2 DL without nominals -- of Horrocks, Kutz and
Sattler ("The even more irresistible SROIQ", KR 2006), with the SHIQ merging of Horrocks,
Sattler and Tobies (1999). A concept is put in negation normal form and a completion
graph is grown from one node until every rule is satisfied (the concept is satisfiable)
or every choice ends in a clash (it is not). In outline:

* conjunctions, disjunctions (branching), existential and qualified minimum restrictions
  (which create successors), maximum restrictions (which merge neighbours, choosing first
  whether each neighbour is in the filler), universal restrictions;
* universal restrictions over a role with property chains or transitivity are propagated
  through the role's automaton, which is what makes a transitive or chained relation
  decidable at all;
* inverse relations, sub-properties, symmetric, asymmetric and disjoint relations, and
  functional and inverse-functional ones as maximum restrictions of one;
* pairwise blocking, so that the graph stays finite.

Two things keep it fast enough on a hand-written ontology: lazy unfolding of every axiom
with a named class on the left, and absorption -- domains become universals over the
inverse relation, ranges become universals everywhere, and an axiom whose left side is an
intersection with a named class is folded into that class. Only what is left becomes a
disjunction on every node.

**What it does not decide, it says.** Nominals (`owl:hasValue`) and reflexive relations
are outside what is implemented, and an ontology using them has those axioms returned in
`outside`; a search that exceeds its budget is returned as `unchecked`. In both cases the
report does not pass, because "nothing was found" and "nothing was looked for" are
different answers and a gate that conflated them would pass every ontology it could not
read.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass, field

from atlas.model.owl import (
    BOTTOM,
    TOP,
    And,
    Axiom,
    Cardinality,
    ClassExpression,
    DisjointClasses,
    DisjointProperties,
    Domain,
    EquivalentClasses,
    EquivalentProperties,
    HasCharacteristic,
    HasValue,
    InverseProperties,
    Named,
    Not,
    Only,
    Or,
    Range,
    Some,
    SubClassOf,
    SubPropertyOf,
)

Role = tuple[str, bool]
"""A relation, and whether it is read backwards."""

MAX_NODES = 400
MAX_BRANCHES = 4000

TOP_C = ("top",)
BOTTOM_C = ("bottom",)


class Budget(Exception):
    """The search needed more nodes or choices than it was given."""


class Irregular(ValueError):
    """A property hierarchy OWL 2 DL does not allow: one no automaton can recognise."""


@dataclass(frozen=True)
class Verdict:
    """What the tableau decided about an ontology."""

    consistent: bool | None
    unsatisfiable: tuple[str, ...] = ()
    satisfiable: tuple[str, ...] = ()
    unchecked: tuple[str, ...] = ()
    outside: tuple[Axiom, ...] = ()

    @property
    def decided(self) -> bool:
        """Whether every question asked was answered, over every axiom."""
        return self.consistent is not None and not self.unchecked and not self.outside


def inv(role: Role) -> Role:
    return (role[0], not role[1])


# ---- negation normal form -----------------------------------------------------------------


def nnf(expression: ClassExpression, negated: bool = False) -> tuple:
    """A class expression as a tuple in negation normal form."""
    if isinstance(expression, Named):
        if expression.name == TOP:
            return BOTTOM_C if negated else TOP_C
        if expression.name == BOTTOM:
            return TOP_C if negated else BOTTOM_C
        return ("not", expression.name) if negated else ("atom", expression.name)
    if isinstance(expression, Not):
        return nnf(expression.operand, not negated)
    if isinstance(expression, And | Or):
        conjunctive = isinstance(expression, And) != negated
        parts = frozenset(nnf(one, negated) for one in expression.operands)
        return ("and" if conjunctive else "or", parts)
    role = (expression.property.name, expression.property.inverse)
    if isinstance(expression, Some):
        return ("all", role, nnf(expression.filler, True)) if negated else (
            "some", role, nnf(expression.filler))
    if isinstance(expression, Only):
        return ("some", role, nnf(expression.filler, True)) if negated else (
            "all", role, nnf(expression.filler))
    if isinstance(expression, Cardinality):
        filler = nnf(expression.filler)
        n = expression.count
        if expression.bound == "exactly":
            both = And(operands=(
                Cardinality(bound="min", count=n, property=expression.property,
                            filler=expression.filler),
                Cardinality(bound="max", count=n, property=expression.property,
                            filler=expression.filler)))
            return nnf(both, negated)
        if expression.bound == "min":
            if negated:
                return ("max", n - 1, role, filler) if n > 0 else BOTTOM_C
            return ("min", n, role, filler) if n > 0 else TOP_C
        if negated:
            return ("min", n + 1, role, filler)
        return ("max", n, role, filler)
    raise ValueError(f"not decidable here: {expression.text()}")


def negate(concept: tuple) -> tuple:
    """The negation normal form of the complement of a concept already in that form."""
    kind = concept[0]
    if kind == "top":
        return BOTTOM_C
    if kind == "bottom":
        return TOP_C
    if kind == "atom":
        return ("not", concept[1])
    if kind == "not":
        return ("atom", concept[1])
    if kind == "and":
        return ("or", frozenset(negate(one) for one in concept[1]))
    if kind == "or":
        return ("and", frozenset(negate(one) for one in concept[1]))
    if kind == "some":
        return ("all", concept[1], negate(concept[2]))
    if kind == "all":
        return ("some", concept[1], negate(concept[2]))
    if kind == "min":
        return ("max", concept[1] - 1, concept[2], concept[3]) if concept[1] > 0 else BOTTOM_C
    if kind == "max":
        return ("min", concept[1] + 1, concept[2], concept[3])
    raise ValueError(f"cannot negate {concept!r}")


# ---- the TBox and RBox, prepared ----------------------------------------------------------


@dataclass
class Prepared:
    """The ontology in the form the rules read it."""

    unfold: dict[str, set[tuple]] = field(default_factory=dict)       # A ⊑ C, lazily
    unfold_not: dict[str, set[tuple]] = field(default_factory=dict)   # ¬A ⊑ C, lazily
    globals: set[tuple] = field(default_factory=set)                  # on every node
    below: dict[Role, set[Role]] = field(default_factory=dict)        # R -> every S ⊑* R
    automata: dict[Role, _Automaton] = field(default_factory=dict)
    asymmetric: set[str] = field(default_factory=set)
    disjoint_roles: list[tuple[Role, Role]] = field(default_factory=list)
    outside: list[Axiom] = field(default_factory=list)

    def sub(self, role: Role, of: Role) -> bool:
        return role in self.below.get(of, {of})


def prepare(axioms: Iterable[Axiom]) -> Prepared:
    p = Prepared()
    inclusions: list[tuple[tuple, tuple]] = []   # (sub, sup) in NNF, general
    simple: list[tuple[Role, Role]] = []
    chains: list[tuple[tuple[Role, ...], Role]] = []
    for axiom in axioms:
        try:
            _take(axiom, p, inclusions, simple, chains)
        except ValueError:
            p.outside.append(axiom)
    p.below = _hierarchy(simple)
    for sub, sup in inclusions:
        _absorb(sub, sup, p)
    p.automata = _automata(p, chains)
    return p


def _take(axiom: Axiom, p: Prepared, inclusions: list, simple: list, chains: list) -> None:
    if isinstance(axiom, SubClassOf):
        _check(axiom.sub)
        _check(axiom.sup)
        inclusions.append((nnf(axiom.sub), nnf(axiom.sup)))
    elif isinstance(axiom, EquivalentClasses):
        for one in axiom.classes:
            _check(one)
        for first in axiom.classes:
            for second in axiom.classes:
                if first is not second:
                    inclusions.append((nnf(first), nnf(second)))
    elif isinstance(axiom, DisjointClasses):
        for one in axiom.classes:
            _check(one)
        for index, first in enumerate(axiom.classes):
            for second in axiom.classes[index + 1:]:
                inclusions.append((nnf(first), nnf(second, True)))
    elif isinstance(axiom, Domain):
        _check(axiom.domain)
        inclusions.append((("some", (axiom.property, False), TOP_C), nnf(axiom.domain)))
    elif isinstance(axiom, Range):
        _check(axiom.range)
        p.globals.add(("all", (axiom.property, False), nnf(axiom.range)))
    elif isinstance(axiom, SubPropertyOf):
        roles = tuple((one.name, one.inverse) for one in axiom.sub)
        sup = (axiom.sup.name, axiom.sup.inverse)
        if len(roles) == 1:
            simple.append((roles[0], sup))
        else:
            chains.append((roles, sup))
    elif isinstance(axiom, EquivalentProperties):
        props = [(one.name, one.inverse) for one in axiom.properties]
        for first in props:
            for second in props:
                if first != second:
                    simple.append((first, second))
    elif isinstance(axiom, InverseProperties):
        simple += [((axiom.first, False), (axiom.second, True)),
                   ((axiom.second, False), (axiom.first, True))]
    elif isinstance(axiom, DisjointProperties):
        props = [(one.name, one.inverse) for one in axiom.properties]
        for index, first in enumerate(props):
            for second in props[index + 1:]:
                p.disjoint_roles.append((first, second))
    elif isinstance(axiom, HasCharacteristic):
        role = (axiom.property, False)
        kind = axiom.characteristic
        if kind == "transitive":
            chains.append(((role, role), role))
        elif kind == "symmetric":
            simple.append((role, inv(role)))
        elif kind == "asymmetric":
            p.asymmetric.add(axiom.property)
        elif kind == "irreflexive":
            # A tree-shaped model never relates a node to itself, and without nominals or
            # self-restrictions none of the rules below can make it, so nothing is lost.
            pass
        elif kind == "functional":
            p.globals.add(("max", 1, role, TOP_C))
        elif kind == "inverse-functional":
            p.globals.add(("max", 1, inv(role), TOP_C))
        else:
            raise ValueError(kind)
    else:
        raise ValueError(type(axiom).__name__)


def _check(expression: ClassExpression) -> None:
    if isinstance(expression, HasValue):
        raise ValueError("nominal")
    if isinstance(expression, And | Or):
        for one in expression.operands:
            _check(one)
    elif isinstance(expression, Not):
        _check(expression.operand)
    elif isinstance(expression, Some | Only | Cardinality):
        _check(expression.filler)


def _absorb(sub: tuple, sup: tuple, p: Prepared) -> None:
    """Fold an inclusion into lazy unfolding where it is sound to, and globalise the rest."""
    kind = sub[0]
    if kind == "atom":
        p.unfold.setdefault(sub[1], set()).add(sup)
        return
    if kind == "not":
        p.unfold_not.setdefault(sub[1], set()).add(sup)
        return
    if kind == "top":
        p.globals.add(sup)
        return
    if kind == "bottom":
        return
    if kind == "or":
        for one in sub[1]:
            _absorb(one, sup, p)
        return
    if kind == "and":
        # B ⊓ rest ⊑ D is B ⊑ ¬rest ⊔ D: attached to B, it fires only where B holds.
        named = sorted((one for one in sub[1] if one[0] == "atom"), key=repr)
        if named:
            first = named[0]
            rest = [one for one in sub[1] if one != first]
            alternatives = frozenset([*(negate(one) for one in rest), sup])
            p.unfold.setdefault(first[1], set()).add(
                ("or", alternatives) if len(alternatives) > 1 else next(iter(alternatives)))
            return
    if kind == "some" and sub[2] in (TOP_C,):
        # ∃R.⊤ ⊑ D -- a domain -- is ⊤ ⊑ ∀R⁻.D: a universal on every node, no choice.
        p.globals.add(("all", inv(sub[1]), sup))
        return
    if kind == "some" and sub[2][0] == "atom":
        # ∃R.A ⊑ D is A ⊑ ∀R⁻.D, which fires only where A holds.
        p.unfold.setdefault(sub[2][1], set()).add(("all", inv(sub[1]), sup))
        return
    p.globals.add(("or", frozenset([negate(sub), sup])))


def _hierarchy(simple: list[tuple[Role, Role]]) -> dict[Role, set[Role]]:
    """Every role with every role below it, itself and inverses included."""
    edges: dict[Role, set[Role]] = {}
    for sub, sup in simple:
        edges.setdefault(sup, set()).add(sub)
        edges.setdefault(inv(sup), set()).add(inv(sub))
    below: dict[Role, set[Role]] = {}
    for role in list(edges):
        seen, frontier = {role}, [role]
        while frontier:
            for sub in edges.get(frontier.pop(), ()):
                if sub not in seen:
                    seen.add(sub)
                    frontier.append(sub)
        below[role] = seen
    return below


# ---- automata for chains and transitivity -------------------------------------------------


@dataclass
class _Automaton:
    """A finite automaton over roles: the paths that count as one step of a role."""

    initial: int
    finals: set[int]
    moves: dict[int, list[tuple[Role | None, int]]] = field(default_factory=dict)

    def after(self, state: int) -> list[tuple[Role | None, int]]:
        return self.moves.get(state, [])


def _automata(p: Prepared, chains: list[tuple[tuple[Role, ...], Role]]) -> dict[Role, _Automaton]:
    """An automaton for every role some chain or transitivity makes non-simple.

    Built as in Horrocks, Kutz and Sattler: a role's automaton accepts the role itself, and
    every sequence of roles a chain axiom makes a path of it, with the automata of the
    roles along that chain spliced in. A universal over a role with an automaton walks the
    automaton instead of one edge, which is how "everything reachable over part_of, at any
    remove" is a finite rule.
    """
    by_sup: dict[Role, list[tuple[Role, ...]]] = {}
    for roles, sup in chains:
        by_sup.setdefault(sup, []).append(roles)
        by_sup.setdefault(inv(sup), []).append(tuple(inv(r) for r in reversed(roles)))
    composite = set(by_sup)
    for role, below in list(p.below.items()):
        if any(one in by_sup for one in below):
            composite.add(role)
    built: dict[Role, _Automaton] = {}
    counter = [0]

    def fresh() -> int:
        counter[0] += 1
        return counter[0]

    def build(role: Role, visiting: tuple[Role, ...]) -> _Automaton:
        if role in visiting:
            raise Irregular(f"the property hierarchy through {role[0]} is not regular")
        start, end = fresh(), fresh()
        automaton = _Automaton(initial=start, finals={end})

        def move(source: int, label: Role | None, target: int) -> None:
            automaton.moves.setdefault(source, []).append((label, target))

        def path(source: int, roles: tuple[Role, ...], target: int) -> None:
            current = source
            for index, one in enumerate(roles):
                nxt = target if index == len(roles) - 1 else fresh()
                splice(current, one, nxt)
                current = nxt

        def splice(source: int, one: Role, target: int) -> None:
            # A role that is itself composite (and is not this one) is replaced by a copy
            # of its own automaton, so its chains count here too.
            if one != role and one in composite and one not in visiting:
                inner = build(one, (*visiting, role))
                offset = fresh() * 10000
                for state, moves in inner.moves.items():
                    for label, nxt in moves:
                        move(state + offset, label, nxt + offset)
                move(source, None, inner.initial + offset)
                for final in inner.finals:
                    move(final + offset, None, target)
            else:
                move(source, one, target)

        move(start, role, end)
        for sub in p.below.get(role, {role}):
            if sub != role and sub in composite:
                splice(start, sub, end)
        for roles in by_sup.get(role, ()):
            if roles == (role, role):
                move(end, None, start)
            elif roles[0] == role:
                path(end, roles[1:], end)
            elif roles[-1] == role:
                path(start, roles[:-1], start)
            else:
                path(start, roles, end)
        return automaton

    for role in composite:
        built[role] = build(role, ())
    return built


# ---- the completion graph -----------------------------------------------------------------


@dataclass
class _Graph:
    labels: list[set] = field(default_factory=list)
    parent: list[int | None] = field(default_factory=list)
    edge: list[set] = field(default_factory=list)          # roles on the edge from the parent
    alive: list[bool] = field(default_factory=list)
    distinct: set[frozenset[int]] = field(default_factory=set)

    def add(self, parent: int | None, roles: set, concepts: set) -> int:
        self.labels.append(set(concepts))
        self.parent.append(parent)
        self.edge.append(set(roles))
        self.alive.append(True)
        return len(self.labels) - 1

    def children(self, node: int) -> list[int]:
        return [one for one, up in enumerate(self.parent) if up == node and self.alive[one]]

    def ancestors(self, node: int) -> list[int]:
        found = []
        current = self.parent[node]
        while current is not None:
            found.append(current)
            current = self.parent[current]
        return found


class _Search:
    def __init__(self, prepared: Prepared, max_nodes: int, max_branches: int) -> None:
        self.p = prepared
        self.max_nodes = max_nodes
        self.max_branches = max_branches
        self.branches = 0

    # -- neighbours ---------------------------------------------------------------------

    def neighbours(self, g: _Graph, x: int, role: Role) -> list[int]:
        """Every node related to x by the role or by anything below it, in either direction."""
        found = []
        for child in g.children(x):
            if any(self.p.sub(one, role) for one in g.edge[child]):
                found.append(child)
        up = g.parent[x]
        if up is not None and g.alive[up]:
            if any(self.p.sub(inv(one), role) for one in g.edge[x]):
                found.append(up)
        return found

    def neighbours_by(self, g: _Graph, x: int, label: Role) -> list[int]:
        return self.neighbours(g, x, label)

    # -- blocking -----------------------------------------------------------------------

    def blocked(self, g: _Graph, x: int) -> bool:
        """Pairwise blocking: x and its parent look exactly like an earlier pair."""
        if g.parent[x] is None:
            return False
        ancestors = g.ancestors(x)
        for one in ancestors:
            if self._directly_blocked(g, one, g.ancestors(one)):
                return True
        return self._directly_blocked(g, x, ancestors)

    def _directly_blocked(self, g: _Graph, x: int, ancestors: list[int]) -> bool:
        xp = g.parent[x]
        if xp is None:
            return False
        for y in ancestors:
            yp = g.parent[y]
            if yp is None:
                continue
            if (g.labels[x] == g.labels[y] and g.labels[xp] == g.labels[yp]
                    and g.edge[x] == g.edge[y]):
                return True
        return False

    # -- rules ----------------------------------------------------------------------------

    def clash(self, g: _Graph) -> bool:
        for x, label in enumerate(g.labels):
            if not g.alive[x]:
                continue
            if BOTTOM_C in label:
                return True
            for concept in label:
                if concept[0] == "atom" and ("not", concept[1]) in label:
                    return True
                if concept[0] == "max":
                    n, role, filler = concept[1], concept[2], concept[3]
                    having = [y for y in self.neighbours(g, x, role) if filler in g.labels[y]]
                    if len(having) > n and _all_distinct(g, having, n + 1):
                        return True
            for one in g.edge[x]:
                if one[0] in self.p.asymmetric and inv(one) in g.edge[x]:
                    return True
            for first, second in self.p.disjoint_roles:
                edge = g.edge[x]
                if (any(self.p.sub(one, first) for one in edge)
                        and any(self.p.sub(one, second) for one in edge)):
                    return True
        return False

    def saturate(self, g: _Graph) -> None:
        """Every deterministic rule, to a fixed point."""
        changed = True
        while changed:
            changed = False
            for x in range(len(g.labels)):
                if not g.alive[x] or self._indirectly_blocked(g, x):
                    continue
                label = g.labels[x]
                new: set = set()
                new |= self.p.globals - label
                for concept in list(label):
                    kind = concept[0]
                    if kind == "and":
                        new |= set(concept[1]) - label
                    elif kind == "atom":
                        new |= self.p.unfold.get(concept[1], set()) - label
                    elif kind == "not":
                        new |= self.p.unfold_not.get(concept[1], set()) - label
                    elif kind == "all":
                        role, filler = concept[1], concept[2]
                        automaton = self.p.automata.get(role)
                        if automaton is not None:
                            start = ("walk", role, automaton.initial, filler)
                            if start not in label:
                                new.add(start)
                        else:
                            for y in self.neighbours(g, x, role):
                                if filler not in g.labels[y]:
                                    g.labels[y].add(filler)
                                    changed = True
                    elif kind == "walk":
                        _, role, state, filler = concept
                        automaton = self.p.automata[role]
                        if state in automaton.finals and filler not in label:
                            new.add(filler)
                        for step, nxt in automaton.after(state):
                            walked = ("walk", role, nxt, filler)
                            if step is None:
                                if walked not in label:
                                    new.add(walked)
                                continue
                            for y in self.neighbours_by(g, x, step):
                                if walked not in g.labels[y]:
                                    g.labels[y].add(walked)
                                    changed = True
                if new - label:
                    label |= new
                    changed = True

    def _indirectly_blocked(self, g: _Graph, x: int) -> bool:
        return any(self._directly_blocked(g, one, g.ancestors(one)) for one in g.ancestors(x))

    def expand(self, g: _Graph) -> bool:
        """Whether this graph can be completed without a clash."""
        while True:
            self.saturate(g)
            if self.clash(g):
                return False
            choice = self._choice(g)
            if choice is not None:
                self.branches += 1
                if self.branches > self.max_branches:
                    raise Budget
                for alternative in choice:
                    attempt = copy.deepcopy(g)
                    alternative(attempt)
                    if self.expand(attempt):
                        return True
                return False
            if not self._generate(g):
                return True

    def _choice(self, g: _Graph):  # noqa: ANN202 -- a list of alternatives, or None
        for x in range(len(g.labels)):
            if not g.alive[x] or self._indirectly_blocked(g, x):
                continue
            label = g.labels[x]
            for concept in sorted(label, key=repr):
                if concept[0] == "or" and not (concept[1] & label):
                    return [(lambda graph, x=x, one=one: graph.labels[x].add(one))
                            for one in sorted(concept[1], key=repr)]
                if concept[0] == "max":
                    n, role, filler = concept[1], concept[2], concept[3]
                    near = self.neighbours(g, x, role)
                    for y in near:
                        if filler not in g.labels[y] and negate(filler) not in g.labels[y]:
                            return [(lambda graph, y=y, f=filler: graph.labels[y].add(f)),
                                    (lambda graph, y=y, f=filler: graph.labels[y].add(negate(f)))]
                    having = [y for y in near if filler in g.labels[y]]
                    if len(having) > n:
                        pairs = [(a, b) for i, a in enumerate(having) for b in having[i + 1:]
                                 if frozenset((a, b)) not in g.distinct]
                        if pairs:
                            return [(lambda graph, a=a, b=b, x=x: _merge(graph, x, a, b))
                                    for a, b in pairs]
        return None

    def _generate(self, g: _Graph) -> bool:
        """Add the successors one unsatisfied existential or minimum asks for."""
        for x in range(len(g.labels)):
            if not g.alive[x] or self.blocked(g, x):
                continue
            for concept in sorted(g.labels[x], key=repr):
                if concept[0] == "some":
                    role, filler = concept[1], concept[2]
                    if any(filler in g.labels[y] for y in self.neighbours(g, x, role)):
                        continue
                    self._grow(g, x, role, {filler})
                    return True
                if concept[0] == "min":
                    n, role, filler = concept[1], concept[2], concept[3]
                    having = [y for y in self.neighbours(g, x, role) if filler in g.labels[y]]
                    if len(having) >= n and _all_distinct(g, having, n):
                        continue
                    made = [self._grow(g, x, role, {filler}) for _ in range(n)]
                    for i, a in enumerate(made):
                        for b in made[i + 1:]:
                            g.distinct.add(frozenset((a, b)))
                    return True
        return False

    def _grow(self, g: _Graph, x: int, role: Role, concepts: set) -> int:
        if sum(g.alive) >= self.max_nodes:
            raise Budget
        return g.add(x, {role}, concepts | self.p.globals)


def _all_distinct(g: _Graph, nodes: list[int], n: int) -> bool:
    """Whether some n of these nodes are pairwise known to be different."""
    if n <= 1:
        return len(nodes) >= n
    chosen: list[int] = []
    for one in nodes:
        if all(frozenset((one, other)) in g.distinct for other in chosen):
            chosen.append(one)
            if len(chosen) >= n:
                return True
    return False


def _merge(g: _Graph, x: int, a: int, b: int) -> None:
    """Merge two neighbours of x into one, the one nearer the root surviving."""
    into, gone = (a, b)
    if g.parent[x] == b or (g.parent[into] == x and g.parent[gone] != x):
        into, gone = b, a
    g.labels[into] |= g.labels[gone]
    if g.parent[gone] == x and g.parent[into] == x:
        g.edge[into] |= g.edge[gone]
    elif g.parent[gone] == x and g.parent[x] == into:
        g.edge[x] |= {inv(one) for one in g.edge[gone]}
    for pair in list(g.distinct):
        if gone in pair:
            other = next(iter(pair - {gone}), gone)
            g.distinct.add(frozenset((into, other)))
    _prune(g, gone)


def _prune(g: _Graph, node: int) -> None:
    g.alive[node] = False
    for child in g.children(node):
        _prune(g, child)


# ---- the questions ------------------------------------------------------------------------


def satisfiable(concept: tuple, prepared: Prepared, *, max_nodes: int = MAX_NODES,
                max_branches: int = MAX_BRANCHES) -> bool:
    """Whether something can be an instance of a concept, under the ontology. Raises Budget."""
    search = _Search(prepared, max_nodes, max_branches)
    g = _Graph()
    g.add(None, set(), {concept} | prepared.globals)
    return search.expand(g)


def decide(axioms: Iterable[Axiom], names: Iterable[str], *, max_nodes: int = MAX_NODES,
           max_branches: int = MAX_BRANCHES) -> Verdict:
    """Whether the ontology is consistent, and which of the named classes can have members."""
    axioms = list(axioms)
    try:
        prepared = prepare(axioms)
    except Irregular as irregular:
        return Verdict(consistent=None, unchecked=(str(irregular),))
    outside = tuple(prepared.outside)
    try:
        consistent = satisfiable(TOP_C, prepared, max_nodes=max_nodes,
                                 max_branches=max_branches)
    except Budget:
        return Verdict(consistent=None, unchecked=("consistency",), outside=outside)
    if not consistent:
        return Verdict(consistent=False, outside=outside)
    good: list[str] = []
    bad: list[str] = []
    skipped: list[str] = []
    for name in names:
        try:
            if satisfiable(("atom", name), prepared, max_nodes=max_nodes,
                           max_branches=max_branches):
                good.append(name)
            else:
                bad.append(name)
        except Budget:
            skipped.append(name)
    return Verdict(consistent=True, unsatisfiable=tuple(bad), satisfiable=tuple(good),
                   unchecked=tuple(skipped), outside=outside)


def subsumed(sub: ClassExpression, sup: ClassExpression, axioms: Iterable[Axiom]) -> bool:
    """Whether the ontology implies sub ⊑ sup: whether sub ⊓ ¬sup is unsatisfiable."""
    prepared = prepare(list(axioms))
    return not satisfiable(("and", frozenset([nnf(sub), nnf(sup, True)])), prepared)


__all__ = ["Budget", "Irregular", "Prepared", "Verdict", "decide", "nnf", "prepare",
           "satisfiable", "subsumed"]
