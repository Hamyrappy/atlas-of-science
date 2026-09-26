"""OWL 2 EL: classifying an ontology's classes, completely, in polynomial time.

EL is the profile of big terminologies -- SNOMED, the Gene Ontology -- and it is the one in
which classification is both complete and cheap: every subsumption the axioms imply is
found, in time polynomial in their size. That is what makes it the right engine to run
every time an ontology is loaded: the hierarchy `Schema.is_a` answers from is computed
here, so a class that an equivalence, an intersection or an existential restriction makes
a subclass of another is one without anybody having written it as a parent.

The algorithm is the completion procedure of Baader, Brandt and Lutz ("Pushing the EL
envelope", IJCAI 2005), with the range treatment of their 2008 follow-up: axioms are first
normalised into five forms, then two relations are saturated -- `S(C)`, the classes known
to contain C, and `R(r)`, the pairs known to be joined by r -- until nothing more follows.

**Everything outside EL is left out, and said to be left out.** A union on the right, a
complement, a universal restriction, an inverse property, a cardinality: none of them is
EL, and each axiom that uses one is returned in `ignored`. Leaving an axiom out can only
lose subsumptions, never invent one, so what comes back is always true -- and it is
*all* that is true exactly when `ignored` is empty. Two rewritings recover what EL can
still say from a non-EL axiom: a union on the left splits into one axiom per disjunct, and
an intersection on the right into one per conjunct.

Nothing here reads data. Classification is a question about the ontology, and the
answer does not depend on how many nodes were written under it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from atlas.model.owl import (
    BOTTOM,
    TOP,
    And,
    Axiom,
    ClassExpression,
    DisjointClasses,
    Domain,
    EquivalentClasses,
    EquivalentProperties,
    HasCharacteristic,
    Named,
    Or,
    Range,
    Some,
    SubClassOf,
    SubPropertyOf,
)

FRESH = "_:el"
"""The prefix of the names normalisation invents. They never leave this module."""


@dataclass(frozen=True)
class Classification:
    """What the axioms imply about the named classes, and which axioms were not read."""

    subsumers: dict[str, frozenset[str]]
    unsatisfiable: frozenset[str]
    ignored: tuple[Axiom, ...] = ()

    @property
    def complete(self) -> bool:
        """Whether every axiom was EL, so that every implied subsumption was found."""
        return not self.ignored

    def hierarchy(self) -> dict[str, tuple[str, ...]]:
        """Each named class with its named superclasses, sorted, itself excluded."""
        return {name: tuple(sorted(found - {name})) for name, found in self.subsumers.items()}


def classify(axioms: Iterable[Axiom], names: Iterable[str] = ()) -> Classification:
    """Every named superclass of every named class, and every class nothing can be.

    `names` are the classes to report on; any class an axiom mentions is reported too.
    """
    normal = _Normaliser()
    ignored: list[Axiom] = []
    for axiom in axioms:
        if not normal.add(axiom):
            ignored.append(axiom)
    wanted = {name for name in names if name not in (TOP, BOTTOM)} | {
        name for name in normal.mentioned if name not in (TOP, BOTTOM)
        and not name.startswith(FRESH)
    }
    engine = _Completion(normal)
    for name in sorted(wanted):
        engine.context(name)
    engine.run()
    subsumers = {
        name: frozenset(
            one for one in engine.S[name] if one not in (TOP, BOTTOM) and not one.startswith(FRESH)
        )
        for name in wanted
    }
    unsatisfiable = frozenset(name for name in wanted if BOTTOM in engine.S[name])
    return Classification(subsumers=subsumers, unsatisfiable=unsatisfiable,
                          ignored=tuple(ignored))


# ---- normalisation ------------------------------------------------------------------------


@dataclass
class _Normaliser:
    """The axioms, rewritten into the five normal forms the completion rules read."""

    nf1: list[tuple[frozenset[str], str]] = field(default_factory=list)   # A1 ⊓ .. ⊑ B
    nf2: list[tuple[str, str, str]] = field(default_factory=list)          # A ⊑ ∃r.B
    nf3: list[tuple[str, str, str]] = field(default_factory=list)          # ∃r.A ⊑ B
    roles: list[tuple[str, str]] = field(default_factory=list)             # r ⊑ s
    chains: list[tuple[str, str, str]] = field(default_factory=list)       # r1 ∘ r2 ⊑ s
    ranges: dict[str, list[str]] = field(default_factory=dict)             # range(r) ⊑ B
    mentioned: set[str] = field(default_factory=set)
    _count: int = 0

    def add(self, axiom: Axiom) -> bool:
        """Take one axiom in, or answer False if EL cannot say it."""
        if isinstance(axiom, SubClassOf):
            return self._subclass(axiom.sub, axiom.sup)
        if isinstance(axiom, EquivalentClasses):
            pairs = zip(axiom.classes, axiom.classes[1:], strict=False)
            results = [self._subclass(a, b) & self._subclass(b, a) for a, b in pairs]
            return all(results)
        if isinstance(axiom, DisjointClasses):
            if not all(_is_el(one) for one in axiom.classes):
                return False
            for index, first in enumerate(axiom.classes):
                for second in axiom.classes[index + 1:]:
                    self._subclass(And(operands=(first, second)), Named(name=BOTTOM))
            return True
        if isinstance(axiom, SubPropertyOf):
            if any(one.inverse for one in (*axiom.sub, axiom.sup)):
                return False
            names = [one.name for one in axiom.sub]
            if len(names) == 1:
                self.roles.append((names[0], axiom.sup.name))
                return True
            # A longer chain becomes a sequence of binary ones through fresh roles.
            current = names[0]
            for index, following in enumerate(names[1:], start=1):
                target = axiom.sup.name if index == len(names) - 1 else self._fresh()
                self.chains.append((current, following, target))
                current = target
            return True
        if isinstance(axiom, EquivalentProperties):
            if any(one.inverse for one in axiom.properties):
                return False
            for first, second in zip(axiom.properties, axiom.properties[1:], strict=False):
                self.roles += [(first.name, second.name), (second.name, first.name)]
            return True
        if isinstance(axiom, HasCharacteristic):
            if axiom.characteristic != "transitive":
                return False
            self.chains.append((axiom.property, axiom.property, axiom.property))
            return True
        if isinstance(axiom, Domain):
            return self._subclass(Some(property=_role(axiom.property)), axiom.domain)
        if isinstance(axiom, Range):
            if not _is_el(axiom.range):
                return False
            self.ranges.setdefault(axiom.property, []).append(self._basic_above(axiom.range))
            return True
        return False

    def _subclass(self, sub: ClassExpression, sup: ClassExpression) -> bool:
        # What EL can still say about a non-EL axiom: a union on the left is one axiom per
        # disjunct, an intersection on the right is one axiom per conjunct.
        if isinstance(sub, Or):
            return all([self._subclass(one, sup) for one in sub.operands])
        if isinstance(sup, And):
            return all([self._subclass(sub, one) for one in sup.operands])
        if not (_is_el(sub) and _is_el(sup)):
            return False
        self._mention(sub)
        self._mention(sup)
        self._normalise(sub, sup)
        return True

    def _normalise(self, sub: ClassExpression, sup: ClassExpression) -> None:
        if isinstance(sup, And):
            for one in sup.operands:
                self._normalise(sub, one)
            return
        if isinstance(sup, Named) and sup.name == TOP:
            return
        if isinstance(sub, Named) and sub.name == BOTTOM:
            return
        if isinstance(sup, Some):
            left = self._basic_below(sub)
            self.nf2.append((left, sup.property.name, self._basic_above(sup.filler)))
            return
        # sup is a basic concept from here on.
        right = sup.name if isinstance(sup, Named) else self._basic_above(sup)
        if isinstance(sub, Named):
            self.nf1.append((frozenset({sub.name}), right))
        elif isinstance(sub, Some):
            self.nf3.append((sub.property.name, self._basic_below(sub.filler), right))
        elif isinstance(sub, And):
            conjuncts = set()
            for one in sub.operands:
                if isinstance(one, Named) and one.name == BOTTOM:
                    return
                conjuncts.add(self._basic_below(one))
            self.nf1.append((frozenset(conjuncts), right))

    def _basic_below(self, expression: ClassExpression) -> str:
        """A name standing for an expression on the left of an inclusion: expr ⊑ name."""
        if isinstance(expression, Named):
            return expression.name
        name = self._fresh()
        self._normalise(expression, Named(name=name))
        return name

    def _basic_above(self, expression: ClassExpression) -> str:
        """A name standing for an expression on the right of an inclusion: name ⊑ expr."""
        if isinstance(expression, Named):
            return expression.name
        name = self._fresh()
        self._normalise(Named(name=name), expression)
        return name

    def _fresh(self) -> str:
        self._count += 1
        return f"{FRESH}{self._count}"

    def _mention(self, expression: ClassExpression) -> None:
        if isinstance(expression, Named):
            self.mentioned.add(expression.name)
        elif isinstance(expression, And):
            for one in expression.operands:
                self._mention(one)
        elif isinstance(expression, Some):
            self._mention(expression.filler)


def _is_el(expression: ClassExpression) -> bool:
    if isinstance(expression, Named):
        return True
    if isinstance(expression, And):
        return all(_is_el(one) for one in expression.operands)
    if isinstance(expression, Some):
        return not expression.property.inverse and _is_el(expression.filler)
    return False


def _role(name: str):  # noqa: ANN202 -- a Property, built where it is needed
    from atlas.model.owl import Property

    return Property(name=name)


# ---- completion ---------------------------------------------------------------------------


class _Completion:
    """The saturation of S and R under the completion rules CR1 to CR6."""

    def __init__(self, normal: _Normaliser) -> None:
        self._fillers: dict[tuple[str, str], str] = {}
        self._normal = normal
        self.S: dict[str, set[str]] = {}
        self.succ: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.pred: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.by_conjunct: dict[str, list[tuple[frozenset[str], str]]] = defaultdict(list)
        for conjuncts, result in normal.nf1:
            for one in conjuncts:
                self.by_conjunct[one].append((conjuncts, result))
        self.existential: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.supers = _closure(normal.roles)
        self.ranges: dict[str, list[str]] = defaultdict(list)
        for role, named in normal.ranges.items():
            self.ranges[role] += named
        for left, role, filler in normal.nf2:
            self.existential[left].append((role, self._with_range(role, filler)))
        self.lhs: dict[tuple[str, str], list[str]] = defaultdict(list)
        for role, filler, result in normal.nf3:
            self.lhs[(role, filler)].append(result)
        self.first: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.second: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for one, two, result in normal.chains:
            self.first[one].append((two, result))
            self.second[two].append((one, result))
        self.queue: list[tuple] = []

    def _with_range(self, role: str, filler: str) -> str:
        """The filler of an existential over `role`, narrowed by every range that applies.

        A range of r or of anything above r holds of every r-successor. Folding it into
        the filler -- a fresh name below both -- is what lets the rules below see it.
        """
        applicable = sorted({named for above in self.supers.get(role, {role})
                             for named in self.ranges.get(above, ())})
        if not applicable:
            return filler
        key = (filler, "\x00".join(applicable))
        if key not in self._fillers:
            fresh = self._normal._fresh()
            for one in (filler, *applicable):
                self.by_conjunct[fresh].append((frozenset({fresh}), one))
            self._fillers[key] = fresh
        return self._fillers[key]

    def context(self, name: str) -> None:
        if name in self.S:
            return
        self.S[name] = set()
        self._add_s(name, name)
        self._add_s(name, TOP)

    def run(self) -> None:
        while self.queue:
            event = self.queue.pop()
            if event[0] == "S":
                self._on_s(event[1], event[2])
            else:
                self._on_r(event[1], event[2], event[3])

    def _add_s(self, context: str, name: str) -> None:
        if name not in self.S[context]:
            self.S[context].add(name)
            self.queue.append(("S", context, name))

    def _add_r(self, role: str, source: str, target: str) -> None:
        for above in self.supers.get(role, {role}):
            if target not in self.succ[above][source]:
                self.succ[above][source].add(target)
                self.pred[above][target].add(source)
                self.queue.append(("R", above, source, target))

    def _on_s(self, context: str, name: str) -> None:
        for conjuncts, result in self.by_conjunct.get(name, ()):
            if conjuncts <= self.S[context]:
                self._add_s(context, result)
        for role, filler in self.existential.get(name, ()):
            self.context(filler)
            self._add_r(role, context, filler)
        for role, sources in list(self.pred.items()):
            for source in list(sources.get(context, ())):
                for result in self.lhs.get((role, name), ()):
                    self._add_s(source, result)
                if name == BOTTOM:
                    self._add_s(source, BOTTOM)

    def _on_r(self, role: str, source: str, target: str) -> None:
        for name in list(self.S[target]):
            for result in self.lhs.get((role, name), ()):
                self._add_s(source, result)
        if BOTTOM in self.S[target]:
            self._add_s(source, BOTTOM)
        for following, result in self.first.get(role, ()):
            for beyond in list(self.succ[following].get(target, ())):
                self._add_r(result, source, beyond)
        for preceding, result in self.second.get(role, ()):
            for before in list(self.pred[preceding].get(source, ())):
                self._add_r(result, before, target)


def _closure(pairs: Sequence[tuple[str, str]]) -> dict[str, set[str]]:
    """Each role with every role above it, itself included."""
    above: dict[str, set[str]] = defaultdict(set)
    for sub, sup in pairs:
        above[sub].add(sup)
    closed: dict[str, set[str]] = {}
    for role in list(above):
        seen, frontier = {role}, [role]
        while frontier:
            for sup in above.get(frontier.pop(), ()):
                if sup not in seen:
                    seen.add(sup)
                    frontier.append(sup)
        closed[role] = seen
    return closed


__all__ = ["Classification", "classify"]
