"""What a retraction reaches: everything that stands, directly or not, on one thing.

"A dataset was withdrawn. A script had a bug. Which of our conclusions are now in
question?" is the one question that makes a computational-provenance layer worth
recording, and it is a graph closure: follow the dependency relations backwards from
the thing that failed and collect everything that came to rest on it.

What this step does *not* do is as important. It does not delete, retract, mark or
supersede anything: writing is asserting, and deciding that a conclusion is wrong is a
judgement somebody makes and records as a new assertion. This produces the list of
things that judgement would have to consider, with the path from each of them back to
the cause, so the judgement can be made per item and defended.

Three properties the closure is built to have:

**A path, not a set.** Every affected node comes back with the chain that connects it
to the cause. A list of ids is an alarm; a list of chains is something a person can act
on, and it is what distinguishes "this rests on the retracted table" from "this is two
hops from something that mentions it".

**Cycles terminate.** Dependency graphs extracted from prose contain cycles, because
prose does. The walk visits each node once.

**A budget that runs out is reported.** A closure that silently stopped at a hundred
nodes would say a retraction was contained when nobody looked.
"""

from __future__ import annotations

from pydantic import Field

from atlas.model import Frozen, Node
from atlas.steps import State, register
from atlas.steps.entail import implied, widen
from atlas.walk import LIMIT, Adjacency, Walk, reach

DEPTH = 6
"""How far a dependency chain is followed by default. Deeper than the two hops a
question is answered over, because a dependency chain is long by nature: a result rests
on a computation that read a dataset that was produced by another computation."""


class Affected(Frozen):
    """One thing that rests on the cause, and the chain by which it does."""

    node: Node
    distance: int
    through: tuple[str, ...] = Field(default=(), description="Predicates crossed, cause last")

    @property
    def direct(self) -> bool:
        """Whether it rests on the cause itself rather than on something that does."""
        return self.distance == 1


class LineageOptions(Frozen):
    """Which relations carry dependency, how far to follow them, and which way they point.

    `follow` is the pack's own predicates -- what a result was derived from, what a
    computation read, what it ran. `upstream` says the relations point from the
    dependent thing to what it depends on, which is how they are usually written: the
    walk then runs against them, from the cause to what stands on it.
    """

    follow: tuple[str, ...] = Field(min_length=1)
    depth: int = Field(DEPTH, ge=1)
    limit: int = Field(LIMIT, gt=0)
    upstream: bool = True


@register("lineage", requires=("store", "cause"), produces=("affected", "lineage_partial"),
          options=LineageOptions)
def lineage(state: State, options: LineageOptions) -> State:
    """Everything that stands on the cause, with the chain from each of them back to it."""
    store = state["store"]
    causes = state["cause"]
    causes = (causes,) if isinstance(causes, str) else tuple(causes)
    adjacency = Adjacency.of(implied(state), widen(state, options.follow))
    # The relations point from the dependent thing to what it depends on, so reaching
    # what depends on the cause means walking them backwards.
    found = reach(adjacency, causes, depth=options.depth, limit=options.limit,
                  forward=not options.upstream, backward=options.upstream)
    held = {node.id: node for node in store.get_nodes(found.nodes)}
    affected = tuple(
        Affected(node=held[node_id], distance=walk.length, through=_through(walk))
        for node_id, walk in found.walks.items()
        if node_id in held and node_id not in causes
    )
    return {"affected": affected, "lineage_partial": found.partial}


def _through(walk: Walk) -> tuple[str, ...]:
    """The relations the chain crossed, ordered from the affected thing back to the cause."""
    return tuple(reversed(walk.predicates))
