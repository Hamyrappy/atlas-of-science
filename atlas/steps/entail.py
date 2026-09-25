"""Working out what the ontology implies about the markup, and remembering why.

An ontology that says a relation is transitive, that two relations are inverses, that a
line of argument disputing some proposition makes it contested, has said something
executable. This step executes it: the OWL 2 RL engine (`atlas/reason/rl.py`) closes the
nodes and links of the store -- and of the run, when it is called before anything is
written -- under the ontology's axioms, ahead of the question, which is what makes the
consequences cheap to query, and keeps for every one of them the rule, the premises and
the axiom it came from, which is what makes them safe to use.

The engine is named in the options: `rl`, the default, applies every OWL 2 RL rule the
ontology gives it something to apply; `rdfs` applies the four RDFS entailments and nothing
else, which is what the control architecture runs. No other engine may run here, because
no other one can be run over data without inventing individuals nobody mentioned.

What comes out, and the rules that hold of it:

**Derived is never asserted.** `derived` are links, `typings` are nodes the ontology makes
members of a further class, `identities` are pairs it makes one individual, and `clashes`
are sets of facts it says cannot all hold. None of it is written to the store. A derived
link carries the spans of its premises rather than one of its own -- no text says it --
and is marked derived in its own fields. `assert_derived` exists and is off by default; a
run that turns it on records that *the system* inferred this, under an agent of its own.

**Every consequence carries its derivation.** The rule by the OWL 2 RL table's name and by
a word, the premises, and the axiom. A consequence nobody can explain is one nobody can
check, and an answer that quoted one would be quoting the system's own inference back at
the reader as if a source had said it.

**Only admitted premises are used.** A run names which relations may be reasoned from, and
a claim somebody disputes does not become a premise merely by being in the store. A node's
own type is always admitted: it is what the node asserts about itself.

**A contradiction is reported, not repaired.** A clash names the facts that cannot all
hold. Which one is wrong is a reviewer's question, and an engine that dropped one of them
to make the rest consistent would be answering it without saying so.

**Retraction is computed, not assumed.** `invalidated` takes what has been withdrawn and
returns the derivations that no longer stand -- separately from the ones that also follow
from premises that survive, because those are not lost and a step that dropped them would
overstate the damage.

**A relation from a thing to itself, derived by closing a cycle, is not emitted.** The
engine derives it -- an irreflexive relation needs it to find the cycle -- but as a link
in a package it says nothing a reader can use.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Link, Node, Schema, Span
from atlas.reason.facts import SAME, TYPE, Clash, Derivation, Fact
from atlas.reason.rl import MAX_FACTS, RDFS, RL
from atlas.reason.rl import reason as run_rl
from atlas.reason.rl import supported as _supported
from atlas.steps import State, register
from atlas.steps.graph_expand import GraphExpandOptions, expand
from atlas.steps.retrieve import Hit
from atlas.walk import Adjacency

ROUNDS = 32
"""How many rounds the closure runs before it is taken as it stands. A chain longer than
this leaves the closure reported unfinished rather than truncated silently."""

DERIVED = "derived"
"""The field a derived link carries, naming the rule it came from. A reader of the store
must be able to tell an inference from a claim by looking at the object."""

Engine = Literal["rl", "rdfs"]


class Typing(Frozen):
    """A node the ontology makes a member of a further class, and the fact that says so."""

    node_id: str
    type: str
    fact: str


class Identity(Frozen):
    """Two individuals the ontology makes one, and the fact that says so."""

    first: str
    second: str
    fact: str


class Closure(Frozen):
    """Everything one run of the engine produced, and whether it finished.

    `given` is the asserted facts it started from -- link ids and node ids. It is kept
    because support has to be computed from the ground up: a derived relation may be a
    premise of another, and whether a consequence survives a retraction depends on what
    still follows from what somebody actually claimed.
    """

    links: tuple[Link, ...] = ()
    typings: tuple[Typing, ...] = ()
    identities: tuple[Identity, ...] = ()
    clashes: tuple[Clash, ...] = ()
    derivations: tuple[Derivation, ...] = ()
    given: tuple[str, ...] = ()
    ignored: tuple[str, ...] = Field(
        default=(), description="Axioms outside the engine's profile, which it did not apply"
    )
    finished: bool = True

    def __len__(self) -> int:
        return len(self.links) + len(self.typings) + len(self.identities)


class EntailOptions(Frozen):
    """Which engine, which relations may be reasoned from, and how far.

    `premises` empty means every relation, which is the right default for an ontology
    whose axioms were written deliberately. Naming a few is how a run says that only some
    of them may be used as grounds -- the difference between computing what the ontology
    implies and computing what everything in the store implies. `identity` names the
    relations whose assertion makes two individuals one; nothing is one by default.
    """

    engine: Engine = "rl"
    premises: tuple[str, ...] = ()
    identity: tuple[str, ...] = ()
    rounds: int = Field(ROUNDS, ge=1)
    max_facts: int = Field(MAX_FACTS, gt=0)
    assert_derived: bool = False


@register("entail", requires=("store", "schema"),
          produces=("derived", "typings", "identities", "clashes", "derivations", "closure",
                    "closure_finished"),
          options=EntailOptions)
def entail(state: State, options: EntailOptions) -> State:
    """Close the markup under the ontology, with the derivation of every consequence."""
    schema: Schema = state["schema"]
    store = state["store"]
    nodes = _unique([*store.nodes(), *state.get("nodes", ())])
    links = _unique([*store.links(), *state.get("links", ())])
    admitted = tuple(
        link for link in links
        if not options.premises or link.predicate in options.premises
        or link.predicate in options.identity
    )
    closure = close(admitted, schema, rounds=options.rounds, nodes=nodes,
                    engine=options.engine, identity=options.identity,
                    max_facts=options.max_facts)
    # The closure travels whole as well as in pieces: `invalidated` needs the facts it
    # started from, and a step that rebuilt them from the store would be answering about
    # a different snapshot.
    return {"derived": closure.links, "typings": closure.typings,
            "identities": closure.identities, "clashes": closure.clashes,
            "derivations": closure.derivations, "closure": closure,
            "closure_finished": closure.finished}


def close(
    asserted: Iterable[Link],
    schema: Schema,
    rounds: int = ROUNDS,
    *,
    nodes: Iterable[Node] = (),
    engine: Engine = "rl",
    identity: Iterable[str] = (),
    max_facts: int = MAX_FACTS,
) -> Closure:
    """Everything the ontology implies from these links and nodes, with every derivation.

    One consequence may have **several derivations**. A consequence that follows two ways is
    not two consequences -- it has one id, from what it states -- but both derivations are
    kept, because that is exactly what tells a reviewer, after a retraction, whether it has
    fallen or merely lost one of its grounds.
    """
    links = list(asserted)
    nodes = list(nodes)
    facts = [Fact(id=node.id, subject=node.id, predicate=TYPE,
                  object=_name(schema, node.type)) for node in nodes]
    facts += [Fact(id=link.id, subject=link.src, predicate=link.predicate, object=link.dst)
              for link in links]
    result = run_rl(facts, schema.every_axiom(), rules=RDFS if engine == "rdfs" else RL,
                    identity=tuple(identity), rounds=rounds, max_facts=max_facts,
                    schema_version=schema.version)
    spans = _spans(nodes, links, result.derivations)
    derived_links: list[Link] = []
    typings: list[Typing] = []
    identities: list[Identity] = []
    rule_of = {one.link_id: one.rule for one in result.derivations}
    for fact in result.derived():
        if fact.predicate == TYPE:
            typings.append(Typing(node_id=fact.subject, type=fact.object, fact=fact.id))
        elif fact.predicate == SAME:
            identities.append(Identity(first=fact.subject, second=fact.object, fact=fact.id))
        elif fact.subject != fact.object and fact.id in spans:
            derived_links.append(Link(
                id=fact.id, predicate=fact.predicate, src=fact.subject, dst=fact.object,
                spans=spans[fact.id], schema_version=schema.version,
                fields={DERIVED: rule_of.get(fact.id, "")},
            ))
    return Closure(
        links=tuple(derived_links),
        typings=tuple(typings),
        identities=tuple(identities),
        clashes=result.clashes,
        derivations=result.derivations,
        given=result.given,
        ignored=tuple(one.text() for one in result.ignored),
        finished=result.finished,
    )


def supported(closure: Closure, withdrawn: Iterable[str] = ()) -> set[str]:
    """Every fact that still follows from something somebody claimed, after a retraction.

    Built upwards from the given facts that were not withdrawn; see
    `atlas.reason.rl.supported`, which this is, and why marking downwards would leave two
    consequences that support each other standing on nothing.
    """
    from atlas.reason.rl import Closure as Engine

    return _supported(Engine(derivations=closure.derivations, given=closure.given), withdrawn)


def invalidated(
    closure: Closure, withdrawn: Iterable[str]
) -> tuple[tuple[Derivation, ...], tuple[Derivation, ...]]:
    """What falls when these are withdrawn, and what still follows on other grounds.

    Two collections, not one. A consequence derived two ways -- once from a premise that
    has gone and once from premises that have not -- is still derivable, and reporting it
    as lost would overstate what the retraction cost. The second collection is exactly
    those, and a reviewer reads it to know what *not* to recheck.
    """
    stands = supported(closure, withdrawn)
    shaken = [one for one in closure.derivations if one.rests_on(withdrawn)]
    fallen = tuple(one for one in shaken if one.link_id not in stands)
    standing = tuple(one for one in shaken if one.link_id in stands)
    return fallen, standing


@register("graph_expand_entailed", requires=("store", "hits", "derived"), produces=("bundle",),
          options=GraphExpandOptions)
def graph_expand_entailed(state: State, options: GraphExpandOptions) -> State:
    """Walk the asserted relations together with the derived ones, marking which is which."""
    store = state["store"]
    derived: tuple[Link, ...] = state["derived"]
    adjacency = Adjacency.of([*store.links(), *derived], options.follow)
    hits: tuple[Hit, ...] = state["hits"]
    bundle = expand(
        store,
        tuple(hit.node.id for hit in hits),
        options,
        reasons={hit.node.id: f"ranked {hit.score:.3f}" for hit in hits},
        snapshot=getattr(state.get("schema"), "version", "") or "",
        method="graph_expand_entailed",
        adjacency=adjacency,
    )
    return {"bundle": mark(bundle, derived, state.get("typings", ()))}


def mark(bundle, derived: Iterable[Link], typings: Iterable[Typing] = ()):  # noqa: ANN001, ANN201
    """Say which relations of a package nobody claimed, and what the ontology makes each node.

    The package must be able to say which of its relations are inferences, because an
    answer that presents one as a report of a source is the failure this step exists to
    prevent; and an inferred class goes into the reason a node is there, where an answer
    can use it -- "a contested proposition" -- and say it was inferred.
    """
    inferred = {link.id for link in derived}
    reasons = dict(bundle.reasons)
    held = {node.id for node in bundle.nodes}
    classes: dict[str, list[str]] = {}
    for one in typings:
        if one.node_id in held:
            classes.setdefault(one.node_id, []).append(one.type)
    for node_id, names in classes.items():
        said = f"inferred to be {', '.join(sorted(set(names)))}"
        reasons[node_id] = f"{reasons[node_id]}; {said}" if node_id in reasons else said
    return bundle.model_copy(update={
        "derived": tuple(link.id for link in bundle.links if link.id in inferred),
        "reasons": reasons,
    })


def implied(state: State) -> tuple[Link, ...]:
    """The graph as the ontology makes it: the store's links, and what an `entail` step derived.

    When an `entail` step ran earlier in the chain, every link its engine derived is in
    `derived`, marked in its fields and standing on its premises' spans; a step that reads
    relations through this reads them as the ontology makes them, and can still tell which
    ones nobody claimed.
    """
    return (*state["store"].links(), *state.get("derived", ()))


def widen(state: State, names: Iterable[str]) -> tuple[str, ...]:
    """Relation names widened to every relation the loaded ontology makes a kind of one.

    The QL rewriting of a single relation (`atlas.reason.ql.relations`): `observed_under`
    also means whatever the ontology declares a sub-relation of it, or the inverse of one.
    Without a schema the names are returned as written.
    """
    names = tuple(names)
    schema = state.get("schema")
    if schema is None or not names:
        return names
    from atlas.reason.ql import relations

    return relations(schema.every_axiom(), names)


def derived_of(bundle_links: Iterable[Link]) -> Mapping[str, str]:
    """Which links of a package were inferred, and by which rule; the rest are claims."""
    return {link.id: link.fields[DERIVED] for link in bundle_links if DERIVED in link.fields}


def _spans(nodes: list[Node], links: list[Link],
           derivations: Iterable[Derivation]) -> dict[str, tuple[Span, ...]]:
    """What each derived fact stands on: the spans of its first premise that has any.

    No text says the consequence, so it carries the evidence of what it came from. A
    derived fact may itself be a premise, so this runs until every derivation whose
    premises have evidence has lent it to its fact.
    """
    known: dict[str, tuple[Span, ...]] = {one.id: one.spans for one in (*nodes, *links)}
    pending = sorted(derivations, key=lambda one: (one.link_id, one.premises))
    growing = True
    while growing:
        growing = False
        for one in pending:
            if one.link_id in known:
                continue
            found = next((known[p] for p in one.premises if p in known), None)
            if found is not None:
                known[one.link_id] = found
                growing = True
    return known


def _name(schema: Schema, type_name: str) -> str:
    found = schema.find_type(type_name)
    return found.name if found is not None else type_name


def _unique(items: Iterable) -> list:
    seen: dict[str, object] = {}
    for one in items:
        seen.setdefault(one.id, one)
    return list(seen.values())


__all__ = ["DERIVED", "Closure", "EntailOptions", "Identity", "Typing", "close", "derived_of",
           "entail", "graph_expand_entailed", "invalidated", "mark", "supported"]
