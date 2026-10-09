"""OWL 2 RL: forward chaining over the facts, with the derivation of every consequence.

OWL 2 RL is the profile designed to be run as rules over data, and it is the only one
here that reasons over what was extracted rather than over the ontology alone. The reason
is not speed. It is that **no rule of OWL 2 RL invents an individual.** An existential on
the right of an axiom -- "every result was obtained under some condition" -- is not
expressible in the profile, so no rule can conclude "there is a condition nobody
mentioned". Everything the engine derives relates individuals that were already there,
each derived fact stands on facts that each stand on a quote, and the rule the library
lives by -- no provenance, no node -- survives reasoning over data because of this one
property of the profile. EL, QL and DL do not have it, and they run over the ontology or
answer queries without materialising anything.

The rules are those of the OWL 2 RL/RDF rule table (W3C, OWL 2 Profiles, §4.3) that apply
to object properties and classes: domain and range (`prp-dom`, `prp-rng`), symmetric,
asymmetric, irreflexive, transitive, functional and inverse-functional properties,
sub-properties and property chains (`prp-spo1`, `prp-spo2`), equivalent, disjoint and
inverse properties, subclass and equivalent class (`cax-sco`, `cax-eqc`), disjoint
classes (`cax-dw`), intersection, union, existential and universal restrictions,
value restrictions, max-cardinality 0 and 1, complement, and equality (`eq-sym`,
`eq-trans`, `eq-rep-*`). Datatype reasoning is not implemented; nothing here reasons over
literals.

**An axiom outside the profile is left out and named.** A union on the right, a
complement on the left, an existential on the right, `reflexive`: each is returned in
`ignored`. What the engine then derives is still true; it is not everything the ontology
implies, and the closure says so.

**Rounds are rounds.** Each round applies every rule to the facts known when the round
began, so the k-th round finds exactly what needs a derivation k steps deep. A closure cut
short by `rounds` or `max_facts` reports `finished` false rather than passing as complete.

The same engine is the RDFS engine: `rules=RDFS` keeps domain, range, sub-property and
subclass and nothing else, which is RDFS entailment over this model.
"""

from __future__ import annotations

from collections import defaultdict
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
    Property,
    Range,
    Some,
    SubClassOf,
    SubPropertyOf,
)
from atlas.reason.facts import SAME, TYPE, Clash, Derivation, Fact, derived_id

NAMES = {
    "prp-dom": "domain", "prp-rng": "range", "prp-symp": "symmetric",
    "prp-asyp": "asymmetric", "prp-irp": "irreflexive", "prp-trp": "transitive",
    "prp-spo1": "subproperty", "prp-spo2": "chain", "prp-eqp": "equivalent-property",
    "prp-pdw": "disjoint-properties", "prp-inv": "inverse", "prp-fp": "functional",
    "prp-ifp": "inverse-functional", "cax-sco": "subclass", "cax-eqc": "equivalent-class",
    "cax-dw": "disjoint", "cls-int": "intersection", "cls-uni": "union",
    "cls-svf": "some-values", "cls-avf": "all-values", "cls-hv": "has-value",
    "cls-maxc": "max-cardinality", "cls-com": "complement", "cls-nothing": "nothing",
    "eq-sym": "same-as", "eq-trans": "same-as", "eq-rep": "same-as",
}
"""Every rule this engine applies, by its identifier in the OWL 2 RL rule table, with the
word a reader of a derivation is shown. Both travel on every derivation."""

RDFS = frozenset({"prp-dom", "prp-rng", "prp-spo1", "cax-sco"})
"""The rules that are RDFS entailment over this model: rdfs2, rdfs3, rdfs7 and rdfs9."""

RL = frozenset(NAMES)

ROUNDS = 32
MAX_FACTS = 200_000


@dataclass
class Closure:
    """Everything a run of the engine produced, and whether it ran to the end."""

    facts: tuple[Fact, ...] = ()
    derivations: tuple[Derivation, ...] = ()
    clashes: tuple[Clash, ...] = ()
    given: tuple[str, ...] = ()
    ignored: tuple[Axiom, ...] = ()
    finished: bool = True
    rounds: int = 0

    @property
    def consistent(self) -> bool:
        return not self.clashes

    def derived(self) -> tuple[Fact, ...]:
        return tuple(one for one in self.facts if one.derived)


@dataclass
class _Rules:
    """The ontology, compiled into what each rule looks up."""

    domains: dict[str, list[tuple[ClassExpression, str]]] = field(
        default_factory=lambda: defaultdict(list))
    ranges: dict[str, list[tuple[ClassExpression, str]]] = field(
        default_factory=lambda: defaultdict(list))
    characteristics: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    supers: dict[str, list[tuple[Property, str]]] = field(
        default_factory=lambda: defaultdict(list))       # p -> [(q or q⁻, axiom)]
    chains: list[tuple[tuple[Property, ...], Property, str]] = field(default_factory=list)
    inverses: dict[str, list[tuple[str, str]]] = field(default_factory=lambda: defaultdict(list))
    disjoint_properties: list[tuple[Property, Property, str]] = field(default_factory=list)
    subclass: dict[str, list[tuple[str, str]]] = field(default_factory=lambda: defaultdict(list))
    disjoint: dict[str, list[tuple[str, str]]] = field(default_factory=lambda: defaultdict(list))
    general: list[tuple[ClassExpression, ClassExpression, str, str]] = field(
        default_factory=list)                            # (sub, sup, axiom text, rule id)
    ignored: list[Axiom] = field(default_factory=list)


def reason(
    given: Iterable[Fact],
    axioms: Iterable[Axiom],
    *,
    rules: frozenset[str] = RL,
    identity: Iterable[str] = (),
    rounds: int = ROUNDS,
    max_facts: int = MAX_FACTS,
    schema_version: str = "",
) -> Closure:
    """Close the given facts under the ontology's axioms, recording why each consequence holds.

    `identity` names properties whose assertion means the two ends are one individual --
    how a federation says two registries recorded the same thing. It is off by default:
    an identity is the strongest thing a closure can be told, because it copies every
    fact of either individual onto the other, and nothing should be one by accident.
    """
    compiled = _compile(axioms, rules)
    held = _Held()
    for fact in given:
        if fact.predicate in identity:
            fact = fact.model_copy(update={"predicate": SAME})
        held.add(fact)
    given_ids = tuple(sorted(held.by_id))
    engine = _Engine(compiled, held, rules, schema_version)
    delta = list(held.by_id.values())
    finished = False
    done = 0
    while done < max(rounds, 1):
        done += 1
        found = engine.round(delta)
        delta = []
        for fact, derivation in found:
            existing = held.find(fact)
            if existing is None:
                held.add(fact)
                delta.append(fact)
                existing = fact
            engine.record(derivation.model_copy(update={"link_id": existing.id}),
                          existing.derived)
        if len(held.by_id) > max_facts:
            break
        if not delta and not engine.fresh:
            finished = True
            break
        engine.fresh = False
    return Closure(
        facts=tuple(held.by_id[key] for key in sorted(held.by_id)),
        derivations=tuple(sorted(engine.derivations,
                                 key=lambda one: (one.link_id, one.rule_id, one.premises))),
        clashes=tuple(engine.clashes.values()),
        given=given_ids,
        ignored=tuple(compiled.ignored),
        finished=finished,
        rounds=done,
    )


def supported(closure: Closure, withdrawn: Iterable[str] = ()) -> set[str]:
    """Every fact that still follows from something somebody claimed, after a retraction.

    Built upwards from the given facts that were not withdrawn, adding any derived fact
    one of whose derivations has all its premises already standing, until nothing more
    is added. Marking downwards from what was withdrawn would leave two consequences that
    support each other in a circle standing on nothing but themselves.
    """
    gone = set(withdrawn)
    stands = {one for one in closure.given if one not in gone}
    ways: dict[str, list[Derivation]] = defaultdict(list)
    for one in closure.derivations:
        ways[one.link_id].append(one)
    growing = True
    while growing:
        growing = False
        for fact, reasons in ways.items():
            if fact in stands or fact in gone:
                continue
            if any(all(premise in stands for premise in one.premises) for one in reasons):
                stands.add(fact)
                growing = True
    return stands


# ---- compiling the ontology ---------------------------------------------------------------


def _compile(axioms: Iterable[Axiom], rules: frozenset[str]) -> _Rules:
    compiled = _Rules()
    for axiom in axioms:
        if not _take(compiled, axiom, rules):
            compiled.ignored.append(axiom)
    return compiled


def _take(c: _Rules, axiom: Axiom, rules: frozenset[str]) -> bool:
    text = axiom.text()
    if isinstance(axiom, SubClassOf):
        sub, sup = axiom.sub, axiom.sup
        if isinstance(sub, Named) and isinstance(sup, Named) and sub.name != TOP:
            if "cax-sco" not in rules:
                return False
            if sup.name != TOP:
                c.subclass[sub.name].append((sup.name, text))
            return True
        if "cax-sco" in rules and rules != RDFS and _sub(sub) and _sup(sup):
            c.general.append((sub, sup, text, _rule_for(sub, sup)))
            return True
        return False
    if isinstance(axiom, EquivalentClasses):
        if "cax-eqc" not in rules and rules != RL:
            return False
        members = axiom.classes
        if not all(_sub(one) and _sup(one) for one in members):
            return False
        for first in members:
            for second in members:
                if first is second:
                    continue
                if isinstance(first, Named) and isinstance(second, Named):
                    c.subclass[first.name].append((second.name, text))
                else:
                    c.general.append((first, second, text, _rule_for(first, second)))
        return True
    if isinstance(axiom, DisjointClasses):
        if "cax-dw" not in rules or not all(_sub(one) for one in axiom.classes):
            return False
        for index, first in enumerate(axiom.classes):
            for second in axiom.classes[index + 1:]:
                if isinstance(first, Named) and isinstance(second, Named):
                    c.disjoint[first.name].append((second.name, text))
                    c.disjoint[second.name].append((first.name, text))
                else:
                    c.general.append((And(operands=(first, second)), Named(name=BOTTOM),
                                      text, "cax-dw"))
        return True
    if isinstance(axiom, Domain):
        if "prp-dom" not in rules or not _sup(axiom.domain) or (
            rules == RDFS and not isinstance(axiom.domain, Named)
        ):
            return False
        c.domains[axiom.property].append((axiom.domain, text))
        return True
    if isinstance(axiom, Range):
        if "prp-rng" not in rules or not _sup(axiom.range) or (
            rules == RDFS and not isinstance(axiom.range, Named)
        ):
            return False
        c.ranges[axiom.property].append((axiom.range, text))
        return True
    if isinstance(axiom, SubPropertyOf):
        if axiom.chain:
            if "prp-spo2" not in rules:
                return False
            c.chains.append((axiom.sub, axiom.sup, text))
            return True
        if "prp-spo1" not in rules:
            return False
        sub, sup = axiom.sub[0], axiom.sup
        # A sub-property written between inverses is the same inclusion read backwards.
        if sub.inverse:
            sub, sup = sub.inverted(), sup.inverted()
        c.supers[sub.name].append((sup, text))
        return True
    if isinstance(axiom, EquivalentProperties):
        if "prp-eqp" not in rules:
            return False
        for first in axiom.properties:
            for second in axiom.properties:
                if first == second:
                    continue
                sub, sup = (first, second) if not first.inverse else (
                    first.inverted(), second.inverted())
                c.supers[sub.name].append((sup, text))
        return True
    if isinstance(axiom, DisjointProperties):
        if "prp-pdw" not in rules:
            return False
        for index, first in enumerate(axiom.properties):
            for second in axiom.properties[index + 1:]:
                c.disjoint_properties.append((first, second, text))
        return True
    if isinstance(axiom, InverseProperties):
        if "prp-inv" not in rules:
            return False
        c.inverses[axiom.first].append((axiom.second, text))
        c.inverses[axiom.second].append((axiom.first, text))
        return True
    if isinstance(axiom, HasCharacteristic):
        rule = {"transitive": "prp-trp", "symmetric": "prp-symp", "asymmetric": "prp-asyp",
                "irreflexive": "prp-irp", "functional": "prp-fp",
                "inverse-functional": "prp-ifp"}.get(axiom.characteristic)
        if rule is None or rule not in rules:
            return False
        c.characteristics[axiom.property].add(axiom.characteristic)
        return True
    return False


def _sub(expression: ClassExpression) -> bool:
    """Whether an expression may stand on the left of an axiom in OWL 2 RL."""
    if isinstance(expression, Named):
        return expression.name != TOP
    if isinstance(expression, And | Or):
        return all(_sub(one) for one in expression.operands)
    if isinstance(expression, Some):
        filler = expression.filler
        return (isinstance(filler, Named) and filler.name == TOP) or _sub(filler)
    return isinstance(expression, HasValue)


def _sup(expression: ClassExpression) -> bool:
    """Whether an expression may stand on the right of an axiom in OWL 2 RL.

    No existential, no union, no minimum: each would assert that something exists or that
    one of several things is true without saying which, and a rule can only add a fact it
    can name.
    """
    if isinstance(expression, Named):
        return True
    if isinstance(expression, And):
        return all(_sup(one) for one in expression.operands)
    if isinstance(expression, Not):
        return _sub(expression.operand)
    if isinstance(expression, Only):
        return _sup(expression.filler)
    if isinstance(expression, HasValue):
        return True
    if isinstance(expression, Cardinality):
        filler = expression.filler
        return (expression.bound == "max" and expression.count <= 1
                and ((isinstance(filler, Named) and filler.name == TOP) or _sub(filler)))
    return False


def _rule_for(sub: ClassExpression, sup: ClassExpression) -> str:
    """The rule-table name for a general inclusion, by what its two sides are made of."""
    if isinstance(sup, Only):
        return "cls-avf"
    if isinstance(sup, Not):
        return "cls-com"
    if isinstance(sup, Cardinality):
        return "cls-maxc"
    if isinstance(sup, HasValue) or isinstance(sub, HasValue):
        return "cls-hv"
    if isinstance(sub, Some):
        return "cls-svf"
    if isinstance(sub, Or):
        return "cls-uni"
    if isinstance(sub, And) or isinstance(sup, And):
        return "cls-int"
    return "cax-eqc"


# ---- the facts ----------------------------------------------------------------------------


class _Held:
    """The facts, indexed the way the rules look them up."""

    def __init__(self) -> None:
        self.by_id: dict[str, Fact] = {}
        self.keys: dict[tuple[str, str, str], str] = {}
        self.types: dict[str, dict[str, str]] = defaultdict(dict)
        self.out: dict[str, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
        self.inn: dict[str, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))

    def add(self, fact: Fact) -> None:
        if fact.triple in self.keys:
            return
        self.by_id[fact.id] = fact
        self.keys[fact.triple] = fact.id
        if fact.predicate == TYPE:
            self.types[fact.subject][fact.object] = fact.id
        else:
            self.out[fact.predicate][fact.subject][fact.object] = fact.id
            self.inn[fact.predicate][fact.object][fact.subject] = fact.id

    def find(self, fact: Fact) -> Fact | None:
        key = self.keys.get(fact.triple)
        return self.by_id[key] if key is not None else None

    def edges(self, subject: str, prop: Property) -> dict[str, str]:
        """The individuals `subject` reaches over a property expression, with fact ids."""
        table = self.inn if prop.inverse else self.out
        return table.get(prop.name, {}).get(subject, {})

    def individuals(self) -> set[str]:
        found = set(self.types)
        for table in self.out.values():
            for subject, targets in table.items():
                found.add(subject)
                found.update(targets)
        return found


class _Engine:
    """One ontology over one set of facts, applied round by round."""

    def __init__(self, rules: _Rules, held: _Held, active: frozenset[str],
                 schema_version: str) -> None:
        self.c = rules
        self.held = held
        self.active = active
        self.version = schema_version
        self.derivations: list[Derivation] = []
        self._recorded: set[tuple[str, str, tuple[str, ...]]] = set()
        self.clashes: dict[tuple[str, tuple[str, ...]], Clash] = {}
        self.fresh = False
        self._found: list[tuple[Fact, Derivation]] = []

    # -- bookkeeping ------------------------------------------------------------------------

    def record(self, derivation: Derivation, derived: bool) -> None:
        mark = (derivation.link_id, derivation.rule_id, derivation.premises)
        if mark in self._recorded:
            return
        self._recorded.add(mark)
        self.derivations.append(derivation)
        if derived:
            self.fresh = True

    def _emit(self, subject: str, predicate: str, obj: str, rule_id: str,
              premises: Iterable[str], axiom: str = "") -> None:
        if rule_id.split("-")[0] != "eq" and rule_id not in self.active:
            return
        if predicate == TYPE and obj == TOP:
            return
        if predicate == TYPE and obj == BOTTOM:
            self._clash("cls-nothing", subject, premises, axiom,
                        f"{subject} would be an instance of owl:Nothing")
            return
        premises = tuple(sorted(set(premises)))
        fact = Fact(id=derived_id(subject, predicate, obj), subject=subject,
                    predicate=predicate, object=obj, derived=True)
        derivation = Derivation(link_id=fact.id, rule=NAMES.get(rule_id, rule_id),
                                rule_id=rule_id, premises=premises,
                                predicate=predicate, axiom=axiom,
                                schema_version=self.version)
        self._found.append((fact, derivation))

    def _clash(self, rule_id: str, subject: str, premises: Iterable[str], axiom: str,
               detail: str) -> None:
        premises = tuple(sorted(set(premises)))
        # One contradiction, however many facts it was noticed from: the same premises
        # under the same rule are one clash, whichever end the engine looked from.
        key = (rule_id, premises)
        if key not in self.clashes:
            self.clashes[key] = Clash(rule=NAMES.get(rule_id, rule_id), rule_id=rule_id,
                                      subject=subject, premises=premises, axiom=axiom,
                                      detail=detail)

    def _type(self, subject: str, name: str, rule_id: str, premises: Iterable[str],
              axiom: str) -> None:
        self._emit(subject, TYPE, name, rule_id, premises, axiom)

    # -- a round ----------------------------------------------------------------------------

    def round(self, delta: list[Fact]) -> list[tuple[Fact, Derivation]]:
        self._found = []
        touched: set[str] = set()
        for fact in delta:
            touched.add(fact.subject)
            if fact.predicate == TYPE:
                self._on_type(fact)
            elif fact.predicate == SAME:
                touched.add(fact.object)
                self._on_same(fact)
            else:
                touched.add(fact.object)
                self._on_edge(fact)
        self._general(touched)
        return self._found

    def _on_type(self, fact: Fact) -> None:
        x, name = fact.subject, fact.object
        for sup, axiom in self.c.subclass.get(name, ()):
            self._type(x, sup, "cax-sco", (fact.id,), axiom)
        for other, axiom in self.c.disjoint.get(name, ()):
            other_id = self.held.types.get(x, {}).get(other)
            if other_id is not None:
                self._clash("cax-dw", x, (fact.id, other_id), axiom,
                            f"{x} is both {name!r} and {other!r}")
        for same, same_id in self.held.out.get(SAME, {}).get(x, {}).items():
            self._type(same, name, "eq-rep", (fact.id, same_id), "")

    def _on_edge(self, fact: Fact) -> None:
        x, p, y = fact.subject, fact.predicate, fact.object
        for domain, axiom in self.c.domains.get(p, ()):
            self._apply(domain, x, (fact.id,), "prp-dom", axiom)
        for rng, axiom in self.c.ranges.get(p, ()):
            self._apply(rng, y, (fact.id,), "prp-rng", axiom)
        kinds = self.c.characteristics.get(p, set())
        if "symmetric" in kinds:
            self._emit(y, p, x, "prp-symp", (fact.id,), f"SymmetricObjectProperty({p})")
        if "irreflexive" in kinds and x == y:
            self._clash("prp-irp", x, (fact.id,), f"IrreflexiveObjectProperty({p})",
                        f"{x} is related to itself by {p!r}")
        if "asymmetric" in kinds:
            back = self.held.out.get(p, {}).get(y, {}).get(x)
            if back is not None:
                self._clash("prp-asyp", x, (fact.id, back), f"AsymmetricObjectProperty({p})",
                            f"{x} and {y} are related by {p!r} both ways")
        if "transitive" in kinds:
            axiom = f"TransitiveObjectProperty({p})"
            for z, other in self.held.out.get(p, {}).get(y, {}).items():
                self._emit(x, p, z, "prp-trp", (fact.id, other), axiom)
            for w, other in self.held.inn.get(p, {}).get(x, {}).items():
                self._emit(w, p, y, "prp-trp", (other, fact.id), axiom)
        if "functional" in kinds:
            for other_y, other in self.held.out.get(p, {}).get(x, {}).items():
                if other_y != y:
                    self._same(y, other_y, "prp-fp", (fact.id, other),
                               f"FunctionalObjectProperty({p})")
        if "inverse-functional" in kinds:
            for other_x, other in self.held.inn.get(p, {}).get(y, {}).items():
                if other_x != x:
                    self._same(x, other_x, "prp-ifp", (fact.id, other),
                               f"InverseFunctionalObjectProperty({p})")
        for sup, axiom in self.c.supers.get(p, ()):
            if sup.inverse:
                self._emit(y, sup.name, x, "prp-spo1", (fact.id,), axiom)
            else:
                self._emit(x, sup.name, y, "prp-spo1", (fact.id,), axiom)
        for other, axiom in self.c.inverses.get(p, ()):
            self._emit(y, other, x, "prp-inv", (fact.id,), axiom)
        for first, second, axiom in self.c.disjoint_properties:
            for mine, theirs in ((first, second), (second, first)):
                if _matches(mine, fact):
                    other = self._edge_id(theirs, x if not mine.inverse else y,
                                          y if not mine.inverse else x)
                    if other is not None:
                        self._clash("prp-pdw", x, (fact.id, other), axiom,
                                    f"{x} and {y} are related by two disjoint properties")
        for chain, sup, axiom in self.c.chains:
            self._chain(fact, chain, sup, axiom)
        for same, same_id in self.held.out.get(SAME, {}).get(x, {}).items():
            self._emit(same, p, y, "eq-rep", (fact.id, same_id), "")
        for same, same_id in self.held.out.get(SAME, {}).get(y, {}).items():
            self._emit(x, p, same, "eq-rep", (fact.id, same_id), "")

    def _on_same(self, fact: Fact) -> None:
        x, y = fact.subject, fact.object
        if x == y:
            return
        self._emit(y, SAME, x, "eq-sym", (fact.id,))
        for z, other in self.held.out.get(SAME, {}).get(y, {}).items():
            if z != x:
                self._emit(x, SAME, z, "eq-trans", (fact.id, other))
        for name, type_id in self.held.types.get(x, {}).items():
            self._type(y, name, "eq-rep", (fact.id, type_id), "")
        for p, table in list(self.held.out.items()):
            if p == SAME:
                continue
            for z, edge in table.get(x, {}).items():
                self._emit(y, p, z, "eq-rep", (fact.id, edge))
            for w, edge in self.held.inn.get(p, {}).get(x, {}).items():
                self._emit(w, p, y, "eq-rep", (fact.id, edge))

    def _same(self, first: str, second: str, rule_id: str, premises: Iterable[str],
              axiom: str) -> None:
        self._emit(first, SAME, second, rule_id, premises, axiom)

    def _chain(self, fact: Fact, chain: tuple[Property, ...], sup: Property, axiom: str) -> None:
        """Every chain the new fact takes part in, at whichever position it can stand."""
        for position, link in enumerate(chain):
            if not _matches(link, fact):
                continue
            start, end = (fact.subject, fact.object) if not link.inverse else (
                fact.object, fact.subject)
            for before, before_ids in self._walk_back(chain[:position], start):
                for after, after_ids in self._walk(chain[position + 1:], end):
                    premises = (*before_ids, fact.id, *after_ids)
                    if sup.inverse:
                        self._emit(after, sup.name, before, "prp-spo2", premises, axiom)
                    else:
                        self._emit(before, sup.name, after, "prp-spo2", premises, axiom)

    def _walk(self, chain: tuple[Property, ...], start: str) -> list[tuple[str, tuple[str, ...]]]:
        paths = [(start, ())]
        for link in chain:
            paths = [(target, (*ids, edge)) for node, ids in paths
                     for target, edge in self.held.edges(node, link).items()]
        return paths

    def _walk_back(self, chain: tuple[Property, ...],
                   end: str) -> list[tuple[str, tuple[str, ...]]]:
        paths = [(end, ())]
        for link in reversed(chain):
            paths = [(source, (edge, *ids)) for node, ids in paths
                     for source, edge in self.held.edges(node, link.inverted()).items()]
        return paths

    def _edge_id(self, prop: Property, subject: str, obj: str) -> str | None:
        return self.held.out.get(prop.name, {}).get(subject, {}).get(obj)

    # -- class expressions ------------------------------------------------------------------

    def _general(self, touched: set[str]) -> None:
        """Every general inclusion, for every individual whose facts changed and its neighbours.

        An existential on the left of an axiom looks at a neighbour's types, so an
        individual is re-examined when anything it is related to changed as well.
        """
        if not self.c.general:
            return
        affected = set(touched)
        for x in touched:
            for table in (self.held.out, self.held.inn):
                for by_subject in table.values():
                    affected.update(by_subject.get(x, {}))
        for x in sorted(affected):
            for sub, sup, axiom, rule_id in self.c.general:
                witness = self._holds(sub, x)
                if witness is not None:
                    self._apply(sup, x, witness, rule_id, axiom)

    def _holds(self, expression: ClassExpression, x: str) -> tuple[str, ...] | None:
        """The facts that show `x` is an instance of an expression, or None if none do."""
        if isinstance(expression, Named):
            if expression.name == TOP:
                return ()
            found = self.held.types.get(x, {}).get(expression.name)
            return (found,) if found is not None else None
        if isinstance(expression, And):
            premises: list[str] = []
            for one in expression.operands:
                found = self._holds(one, x)
                if found is None:
                    return None
                premises += found
            return tuple(premises)
        if isinstance(expression, Or):
            for one in expression.operands:
                found = self._holds(one, x)
                if found is not None:
                    return found
            return None
        if isinstance(expression, Some):
            for y, edge in sorted(self.held.edges(x, expression.property).items()):
                found = self._holds(expression.filler, y)
                if found is not None:
                    return (edge, *found)
            return None
        if isinstance(expression, HasValue):
            edge = self.held.edges(x, expression.property).get(expression.individual)
            return (edge,) if edge is not None else None
        return None

    def _apply(self, expression: ClassExpression, x: str, premises: tuple[str, ...],
               rule_id: str, axiom: str) -> None:
        """What an expression on the right of an axiom adds about `x`, or the clash it finds."""
        if isinstance(expression, Named):
            self._type(x, expression.name, rule_id, premises, axiom)
        elif isinstance(expression, And):
            for one in expression.operands:
                self._apply(one, x, premises, rule_id, axiom)
        elif isinstance(expression, Not):
            against = self._holds(expression.operand, x)
            if against is not None:
                self._clash("cls-com", x, (*premises, *against), axiom,
                            f"{x} is an instance of {expression.operand.text()}, "
                            "which the ontology excludes")
        elif isinstance(expression, Only):
            for y, edge in sorted(self.held.edges(x, expression.property).items()):
                self._apply(expression.filler, y, (*premises, edge), "cls-avf", axiom)
        elif isinstance(expression, HasValue):
            prop = expression.property
            if prop.inverse:
                self._emit(expression.individual, prop.name, x, "cls-hv", premises, axiom)
            else:
                self._emit(x, prop.name, expression.individual, "cls-hv", premises, axiom)
        elif isinstance(expression, Cardinality):
            targets = [
                (y, (edge, *found))
                for y, edge in sorted(self.held.edges(x, expression.property).items())
                if (found := self._holds(expression.filler, y)) is not None
            ]
            if expression.count == 0 and targets:
                self._clash("cls-maxc", x, (*premises, *targets[0][1]), axiom,
                            f"{x} may have no {expression.property.text()}, and has one")
            elif expression.count == 1:
                for (first, first_ids), (second, second_ids) in zip(
                    targets, targets[1:], strict=False
                ):
                    self._same(first, second, "cls-maxc",
                               (*premises, *first_ids, *second_ids), axiom)


def _matches(prop: Property, fact: Fact) -> bool:
    return fact.predicate == prop.name


__all__ = ["MAX_FACTS", "NAMES", "RDFS", "RL", "ROUNDS", "Closure", "reason", "supported"]
