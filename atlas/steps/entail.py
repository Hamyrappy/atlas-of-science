"""Computing what the relations declared in the pack imply, and remembering why.

A pack that says a relation is transitive has said something executable: if A is part of
B and B is part of C then A is part of C, and a question about A ought to find C without
anybody having asserted the third link. This step computes those consequences ahead of
the question, which is what makes them cheap to query, and keeps for every one of them
the premises and the rule it came from, which is what makes them safe to use.

Four rules, and each is a way a materialisation turns into a lie.

**Derived is never asserted.** What comes back is a separate collection, not a write to
the store. A derived link carries the spans of its premises rather than one of its own,
which is the truthful thing to do since no text says it, and it is marked derived in its
own fields. `assert_derived` exists and is off by default; a run that turns it on is
recording that *the system* inferred this, under an agent of its own.

**Every derived link carries its derivation.** Premises, rule, and the schema version
the rule came from. A consequence nobody can explain is a consequence nobody can check,
and an answer that quoted one would be quoting the system's own inference back at the
reader as if a source had said it.

**Only admitted premises are used.** A run names which relations may be reasoned over,
and a claim somebody disputes does not become a premise merely by being in the store.
"The author disputes P" must not become "not P" anywhere in the graph, and what prevents
that here is that the closure runs over relations the configuration admitted.

**Retraction is computed, not assumed.** `invalidated` takes what has been withdrawn and
returns the derivations that no longer stand -- separately from the ones that also follow
from premises that survive, because those are not lost and a step that dropped them
would overstate the damage.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Link, Schema
from atlas.model.schema import SYMMETRIC, TRANSITIVE
from atlas.steps import State, register
from atlas.steps.graph_expand import GraphExpandOptions, expand
from atlas.steps.retrieve import Hit
from atlas.walk import Adjacency

Rule = Literal["transitive", "symmetric", "inverse"]
"""The consequences this library computes. Three, because these are the three a pack can
declare and a closure can compute without either a reasoner or a decision about what to
do when it fails to terminate."""

ROUNDS = 8
"""How many times a transitive closure is extended before it is taken as it stands. A
chain longer than this leaves the closure reported unfinished rather than truncated
silently."""

DERIVED = "derived"
"""The field a derived link carries, naming the rule it came from. A reader of the store
must be able to tell an inference from a claim by looking at the object."""


class Derivation(Frozen):
    """Why one derived link holds: the rule, what it was derived from, under what schema."""

    link_id: str
    rule: Rule
    premises: tuple[str, ...]
    predicate: str
    schema_version: str = ""

    def rests_on(self, withdrawn: Iterable[str]) -> bool:
        """Whether any of the premises is among what has been withdrawn."""
        return bool(set(self.premises) & set(withdrawn))


class Closure(Frozen):
    """Everything one pass of the closure produced, and whether it finished.

    `given` is the asserted links it started from. It is kept because support has to be
    computed from the ground up: a derived relation may be a premise of another derived
    relation, and asking whether a consequence survives a retraction means asking what
    still follows from what somebody actually claimed.
    """

    links: tuple[Link, ...] = ()
    derivations: tuple[Derivation, ...] = ()
    given: tuple[str, ...] = ()
    finished: bool = True

    def __len__(self) -> int:
        return len(self.links)


class EntailOptions(Frozen):
    """Which relations may be reasoned over, and how far a transitive chain is followed.

    `premises` empty means every relation the pack declares a characteristic for, which
    is the right default for a pack whose RBox was written deliberately. Naming a few is
    how a run says that only some of them may be used as grounds -- the difference
    between computing what the ontology implies and computing what everything in the
    store implies.
    """

    premises: tuple[str, ...] = ()
    rounds: int = Field(ROUNDS, ge=1)
    assert_derived: bool = False


@register("entail", requires=("store", "schema"),
          produces=("derived", "derivations", "closure", "closure_finished"),
          options=EntailOptions)
def entail(state: State, options: EntailOptions) -> State:
    """Compute the relations the pack's own axioms imply, with the derivation of each."""
    schema: Schema = state["schema"]
    asserted = tuple(
        link for link in state["store"].links()
        if not options.premises or link.predicate in options.premises
    )
    closure = close(asserted, schema, rounds=options.rounds)
    # The closure travels whole as well as in pieces: `invalidated` needs the asserted
    # links it started from, and a step that rebuilt them from the store would be
    # answering about a different snapshot.
    return {"derived": closure.links, "derivations": closure.derivations,
            "closure": closure, "closure_finished": closure.finished}


def close(asserted: Iterable[Link], schema: Schema, rounds: int = ROUNDS) -> Closure:
    """Everything the pack's relation axioms imply from these links, with every derivation.

    Runs to a fixed point or to `rounds`, whichever comes first, and says which. The
    three rules are applied together on each round, so a symmetric link can feed a
    transitive chain and an inverse can feed both.

    One relation is one link and may have **several derivations**. A consequence that
    follows two ways is not two consequences -- deduplicating it by what it relates is
    what stops a closure from growing a copy per path -- but both derivations are kept,
    because that is exactly what tells a reviewer, after a retraction, whether the
    consequence has fallen or merely lost one of its grounds.
    """
    held: dict[str, Link] = {link.id: link for link in asserted}
    given = set(held)
    known: dict[tuple[str, str, str], str] = {
        (link.predicate, link.src, link.dst): link.id for link in held.values()
    }
    derivations: list[Derivation] = []
    recorded: set[tuple[str, Rule, tuple[str, ...]]] = set()
    transitive = {p.name for p in schema.with_characteristic(TRANSITIVE)}
    symmetric = {p.name for p in schema.with_characteristic(SYMMETRIC)}
    finished = False
    for _round in range(max(rounds, 1)):
        found = [
            *_symmetric(held.values(), symmetric, schema),
            *_inverse(held.values(), schema),
            *_transitive(held.values(), transitive, schema),
        ]
        fresh = False
        for link, why in found:
            key = (link.predicate, link.src, link.dst)
            existing = known.get(key)
            if existing is None:
                held[link.id] = link
                known[key] = link.id
                existing = link.id
                fresh = True
            why = why.model_copy(update={"link_id": existing})
            mark = (why.link_id, why.rule, why.premises)
            if mark not in recorded:
                recorded.add(mark)
                derivations.append(why)
                fresh = fresh or existing not in given
        if not fresh:
            finished = True
            break
    return Closure(
        links=tuple(held[link_id] for link_id in sorted(held) if link_id not in given),
        derivations=tuple(sorted(derivations, key=lambda one: (one.link_id, one.premises))),
        given=tuple(sorted(given)),
        finished=finished,
    )


def supported(closure: Closure, withdrawn: Iterable[str] = ()) -> set[str]:
    """Every link that still follows from something somebody claimed, after a retraction.

    Computed from the ground up rather than by marking: start with the asserted links
    that were not withdrawn, then repeatedly add any derived link one of whose
    derivations has all its premises already standing, until nothing more is added.

    Building it upwards is what makes it right. A derived relation can be a premise of
    another derived relation, and those can support each other in a circle -- A implies
    B by one rule and B implies A by another. Marking downwards from what was withdrawn
    leaves such a pair standing on nothing but itself, and reports a retraction as
    harmless when it was not.
    """
    gone = set(withdrawn)
    stands = {link_id for link_id in closure.given if link_id not in gone}
    ways: dict[str, list[Derivation]] = {}
    for one in closure.derivations:
        ways.setdefault(one.link_id, []).append(one)
    growing = True
    while growing:
        growing = False
        for link_id, reasons in ways.items():
            if link_id in stands or link_id in gone:
                continue
            if any(all(premise in stands for premise in one.premises) for one in reasons):
                stands.add(link_id)
                growing = True
    return stands


def invalidated(
    closure: Closure, withdrawn: Iterable[str]
) -> tuple[tuple[Derivation, ...], tuple[Derivation, ...]]:
    """What falls when these links are withdrawn, and what still follows on other grounds.

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
    # The package must be able to say which of its relations nobody claimed, because an
    # answer that presents an inference as a report of a source is the failure this
    # architecture exists to prevent.
    inferred = {link.id for link in derived}
    return {"bundle": bundle.model_copy(update={
        "derived": tuple(link.id for link in bundle.links if link.id in inferred),
    })}


def _derived(
    predicate: str, src: str, dst: str, premises: tuple[Link, ...], rule: Rule, schema: Schema
) -> tuple[Link, Derivation]:
    """One consequence and its derivation, standing on the evidence of its premises.

    The spans are the premises' own: no text says the consequence, and inventing one
    would put a claim in the store nothing supports. The id hashes the rule in with the
    rest, so a relation that is both asserted and derivable is two objects and the
    asserted one is not overwritten by the inference.
    """
    spans = premises[0].spans
    material = "\x00".join([rule, src, predicate, dst, *sorted(one.id for one in premises)])
    link = Link(
        id=hashlib.sha256(material.encode("utf-8")).hexdigest()[:16],
        predicate=predicate,
        src=src,
        dst=dst,
        spans=spans,
        schema_version=schema.version,
        fields={DERIVED: rule},
    )
    return link, Derivation(link_id=link.id, rule=rule, predicate=predicate,
                            premises=tuple(sorted(one.id for one in premises)),
                            schema_version=schema.version)


def _transitive(
    links: Iterable[Link], transitive: set[str], schema: Schema
) -> list[tuple[Link, Derivation]]:
    """A -> B -> C becomes A -> C, for the relations the pack declared transitive."""
    by_predicate: dict[str, list[Link]] = {}
    for link in links:
        if link.predicate in transitive:
            by_predicate.setdefault(link.predicate, []).append(link)
    found = []
    for predicate, group in by_predicate.items():
        outgoing: dict[str, list[Link]] = {}
        for link in group:
            outgoing.setdefault(link.src, []).append(link)
        for first in group:
            for second in outgoing.get(first.dst, ()):
                if second.dst == first.src:
                    continue  # A -> B -> A says nothing new and loops the closure.
                found.append(_derived(predicate, first.src, second.dst, (first, second),
                                      "transitive", schema))
    return found


def _symmetric(
    links: Iterable[Link], symmetric: set[str], schema: Schema
) -> list[tuple[Link, Derivation]]:
    """A -> B becomes B -> A, for the relations the pack declared symmetric."""
    return [
        _derived(link.predicate, link.dst, link.src, (link,), "symmetric", schema)
        for link in links
        if link.predicate in symmetric and link.src != link.dst
    ]


def _inverse(links: Iterable[Link], schema: Schema) -> list[tuple[Link, Derivation]]:
    """A -p-> B becomes B -q-> A, where the pack declared q the inverse of p."""
    found = []
    for link in links:
        other = schema.inverse(link.predicate)
        if other is not None:
            found.append(_derived(other.name, link.dst, link.src, (link,), "inverse", schema))
    return found


def derived_of(bundle_links: Iterable[Link]) -> Mapping[str, str]:
    """Which links of a package were inferred, and by which rule; the rest are claims."""
    return {link.id: link.fields[DERIVED] for link in bundle_links if DERIVED in link.fields}
