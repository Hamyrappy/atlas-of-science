"""Recording what a run claims: one assertion per node, appended to a store.

Writing is asserting. Every node is attributed to one agent at one time, so a second
pass over the same source lands under the judgements already recorded instead of
erasing them, and the store projects whichever assertion is currently live. Assertion
ids follow from their content, so replaying an unchanged pass at the same time writes
the assertion it wrote before rather than a second copy of it.
"""

from __future__ import annotations

import hashlib

from atlas.model import Agent, Assertion
from atlas.steps import State, register
from atlas.store.memory import MemoryStore


@register("assert")
def record(state: State, *, agent: str = "run", label: str = "") -> State:
    """Assert every node of the run, into the store it carries or into a new one in memory."""
    store = state.get("store") or MemoryStore()
    at: str = state["at"]
    # A run is identified by the moment it ran; a person or a model by the label they are
    # known under, so that two passes by the same reviewer share one agent id.
    actor = Agent(id=label or f"{agent}:{at}", kind=agent, label=label)
    for source in state["sources"]:
        store.add_source(source)
    assertions = tuple(
        Assertion(id=_assertion_id(actor.id, at, node.id), agent=actor, at=at, target=node)
        for node in state["nodes"]
    )
    for assertion in assertions:
        store.assert_(assertion)
    return {"store": store, "assertions": assertions}


def _assertion_id(agent_id: str, at: str, target_id: str) -> str:
    material = "\x00".join([agent_id, at, target_id])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
