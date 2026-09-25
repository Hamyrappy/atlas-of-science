"""Taking in what other registries published, checking it, and counting confirmations honestly.

A laboratory, a group or a project runs its own Atlas and publishes what it found. This
step reads several of those and builds one local snapshot to answer questions over. Two
things have to be got right, and both of them are places where a federation quietly
becomes worthless.

**Nothing is taken on trust.** Every record that arrives is checked against the source it
claims to come from: the source has to be published with it, and every span has to still
cut its own text out of that source. A record whose evidence does not re-slice is
quarantined with the reason, not merged. That check is cheap because `Span.covers`
already exists -- it is the same rule the rest of this library applies to its own
extraction, applied to somebody else's.

**Two publishers are not two confirmations when they read the same paper.** This is the
error a federation exists to make and has to be built not to make. Independence is
counted over the **sources** behind the claims, not over the registries that published
them: a result republished by three groups from one study is one study. `independence`
returns both numbers so the difference is visible rather than assumed away.

A record whose schema version the local Atlas does not know is **held, not dropped**. It
is a record written under a vocabulary nobody has mapped yet, which is a reason to wait
for the mapping and not a reason to lose the record.

**Two ids are one thing when the ontology says so.** Registries mint their own ids, so one
study published by two of them arrives as two nodes. When an `entail` step has run with an
identity relation named, the OWL 2 RL engine's identities -- two nodes made one
individual, each with the rule and the premises -- are read here, and `individuals` counts
what the package is about after them. Sources are still counted as sources: two papers
reporting one study are two independent reports of it, which is what confirmation is.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import Field

from atlas.model import Assertion, Frozen, Node, Source
from atlas.steps import State, register
from atlas.store import Store, open_store


class Held(Frozen):
    """One record that did not enter the snapshot, with the registry and the reason."""

    origin: str
    assertion_id: str
    target_id: str
    reason: str


class Counted(Frozen):
    """How much independent support something has, and how much merely looks like it."""

    sources: int = Field(description="Distinct sources behind the claims; the honest number")
    registries: int = Field(description="Registries that published them; never the same thing")
    republished: tuple[str, ...] = Field(
        default=(), description="Sources more than one registry published"
    )
    individuals: int = Field(
        0, description="Distinct things the claims are about, once identities are applied"
    )
    identified: tuple[tuple[str, str], ...] = Field(
        default=(), description="Pairs of nodes the ontology made one individual"
    )

    @property
    def independent(self) -> int:
        """What may be called independent support: one source, one count."""
        return self.sources


class FederateOptions(Frozen):
    """Which registries to read, and which schema versions this Atlas knows how to read.

    `registries` is a mapping of a name to a store specification, exactly as a
    configuration names its own store. `versions` empty means every version is accepted;
    naming them is how an Atlas says which vocabularies it has mappings for, and a
    record under any other is held rather than lost.
    """

    registries: dict[str, Any] = Field(
        default_factory=dict,
        description="Name to store specification, or to an already-open store for a caller "
                    "embedding this rather than reading a configuration file",
    )
    versions: tuple[str, ...] = ()
    into: str = Field("memory", description="Store specification the snapshot is built in")


@register("federate", requires=(), produces=("store", "synced", "held", "origins"),
          options=FederateOptions)
def federate(state: State, options: FederateOptions) -> State:
    """Read the registries, check every record, and build the local snapshot from what passes."""
    snapshot: Store = open_store(options.into)
    origins: dict[str, list[str]] = {}
    held: list[Held] = []
    synced = 0
    for name, spec in sorted(options.registries.items()):
        # A string or a mapping is a specification to open; anything else is a store a
        # caller already has. `Store` is a plain Protocol, so this is decided by what the
        # value is rather than by an isinstance check it cannot answer.
        remote: Store = open_store(spec) if isinstance(spec, str | Mapping) else spec
        sources = {source.id: source for source in remote.sources()}
        for assertion in remote.assertions():
            reason = check(assertion, sources, options.versions)
            if reason:
                held.append(Held(origin=name, assertion_id=assertion.id,
                                 target_id=assertion.target.id, reason=reason))
                continue
            source_id = assertion.target.spans[0].source_id
            if snapshot.get_source(source_id) is None:
                snapshot.add_source(sources[source_id])
            snapshot.assert_(assertion)
            synced += 1
            _add(origins.setdefault(assertion.target.id, []), name)
    return {"store": snapshot, "synced": synced, "held": tuple(held),
            "origins": {key: tuple(value) for key, value in origins.items()}}


def check(
    assertion: Assertion, sources: Mapping[str, Source], versions: Iterable[str]
) -> str:
    """Why this record may not enter the snapshot, or an empty string if it may.

    Three questions, in the order that decides what to do about a failure: was the
    source published with it, does its evidence still cut its own text out of that
    source, and is it written under a vocabulary this Atlas can read.
    """
    known = tuple(versions)
    source_id = assertion.target.spans[0].source_id
    source = sources.get(source_id)
    if source is None:
        return f"the registry published no source {source_id!r} for it to stand on"
    for span in assertion.target.spans:
        try:
            text = source.segment_text(span.segment)
        except KeyError:
            return f"segment {span.segment} is not in {source_id!r}"
        if not span.covers(text):
            return (f"evidence at {span.segment}:{span.start}-{span.end} no longer cuts "
                    "its own text out of the source")
    if known and assertion.target.schema_version not in known:
        # Held rather than dropped: a vocabulary nobody has mapped yet is a reason to
        # wait for the mapping, not a reason to lose the record.
        return f"written under schema {assertion.target.schema_version!r}, which is unmapped here"
    return ""


def independence(
    nodes: Iterable[Node],
    origins: Mapping[str, tuple[str, ...]],
    identities: Iterable[tuple[str, str]] = (),
) -> Counted:
    """How much independent support a set of claims has, counted over sources and not publishers.

    The number that matters is the first one. Three registries republishing one study is
    one study, and a federation that counted it three times would manufacture consensus
    out of its own topology -- which is the characteristic failure of federating
    anything. `republished` names the sources that arrived from more than one registry,
    so the gap between the two numbers can be explained rather than argued about.

    `identities` are pairs of node ids an engine made one individual; `individuals` is how
    many distinct things the package holds after them, and `identified` the pairs that
    fell inside it.
    """
    held = tuple(nodes)
    ids = {node.id for node in held}
    parent = {node_id: node_id for node_id in ids}

    def root(node_id: str) -> str:
        while parent[node_id] != node_id:
            parent[node_id] = parent[parent[node_id]]
            node_id = parent[node_id]
        return node_id

    inside = sorted({tuple(sorted(pair)) for pair in identities if set(pair) <= ids
                     and pair[0] != pair[1]})
    for first, second in inside:
        parent[root(first)] = root(second)
    sources = {node.spans[0].source_id for node in held}
    registries: set[str] = set()
    shared: dict[str, set[str]] = {}
    for node in held:
        where = origins.get(node.id, ())
        registries |= set(where)
        shared.setdefault(node.spans[0].source_id, set()).update(where)
    return Counted(
        sources=len(sources),
        registries=len(registries),
        republished=tuple(sorted(name for name, who in shared.items() if len(who) > 1)),
        individuals=len({root(node_id) for node_id in ids}),
        identified=tuple(inside),
    )


@register("count_independence", requires=("bundle", "origins"),
          produces=("independence",))
def count_independence(state: State) -> State:
    """Count how much of the package's support is independent, over the sources behind it.

    Reads `identities` when an `entail` step before it produced them, so what the ontology
    made one individual is counted once.
    """
    pairs = [(one.first, one.second) for one in state.get("identities", ())]
    return {"independence": independence(state["bundle"].nodes, state["origins"], pairs)}


def _add(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)
