"""Recording what a run claims: one assertion per node, appended to a store.

Writing is asserting. Every node is attributed to one agent at one time, so a second
pass over the same source lands under the judgements already recorded instead of
erasing them, and the store projects whichever assertion is currently live. Assertion
ids follow from their content, so replaying an unchanged pass at the same time writes
the assertion it wrote before rather than a second copy of it.

The schema of the run is kept alongside, because every object written here names its
version and a reader a year from now has nothing to resolve that name against otherwise.
The store is whatever the run carries; a run configured with none gets one in memory,
opened by name like any other, so nothing here depends on a particular implementation.

What a configuration may say is who the pass is attributed to, and that is checked when
the file is read: `agent` is one of the three kinds the metamodel knows, so a misspelt
one is refused with the three in the message instead of failing inside `Agent` several
steps into a run that has already ingested and extracted.
"""

from __future__ import annotations

import hashlib

from atlas.model import Agent, AgentKind, Assertion, Frozen
from atlas.steps import State, register
from atlas.store import open_store


class AssertOptions(Frozen):
    """Who the assertions of a pass are attributed to: a kind, and the label it is known by.

    `agent` is the metamodel's own list and not a second copy of it, so the three kinds
    an `Agent` may have are the three a configuration may write. A label is free text
    because it names a person or a model outside this library, and it is what a reviewer
    is identified by: two passes labelled alike share one agent id, an unlabelled pass is
    identified by the moment it ran.
    """

    agent: AgentKind = "run"
    label: str = ""


@register("assert", requires=("sources", "nodes", "schema", "at", "store"),
          produces=("store", "assertions", "agent"), options=AssertOptions)
def record(state: State, options: AssertOptions) -> State:
    """Assert every node and link of the run, into the store it carries or a new one in memory.

    Links are read out of the state rather than required from it, so a configuration
    that extracts no relation keeps working unchanged: a run without them asserts its
    nodes as it always did. A link is asserted exactly as a node is -- same agent, same
    moment, same append-only log -- because a relation is a claim about the world and
    is superseded the same way a claim about a thing is.
    """
    store = state.get("store") or open_store("memory")
    at: str = state["at"]
    # A run is identified by the moment it ran; a person or a model by the label they are
    # known under, so that two passes by the same reviewer share one agent id.
    actor = Agent(id=options.label or f"{options.agent}:{at}", kind=options.agent,
                  label=options.label)
    store.add_schema(state["schema"])
    for source in state["sources"]:
        store.add_source(source)
    assertions = tuple(
        Assertion(id=_assertion_id(actor.id, at, target.id), agent=actor, at=at, target=target)
        for target in (*state["nodes"], *state.get("links", ()))
    )
    for assertion in assertions:
        store.assert_(assertion)
    # The agent travels on: the record of the pass names its author, and only this step knows it.
    return {"store": store, "assertions": assertions, "agent": actor.id}


def _assertion_id(agent_id: str, at: str, target_id: str) -> str:
    material = "\x00".join([agent_id, at, target_id])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
