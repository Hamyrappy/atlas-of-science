"""Walking a body of links: one ruling on what a neighbour is, and what a path is.

Every architecture in `architectures/` is obliged to build its context by walking the
graph rather than by handing a model a list of fragments, and each of them walks it
differently -- diffusion, pruned paths, a prize-collecting tree, a plan of typed
operators. They disagree about which walk is worth doing and agree about everything
underneath it, so that part is here: an adjacency built once out of `Link` objects, a
bounded reach over it, and the walks between two nodes.

Three decisions are made once, in this file, because a variant that made them
differently would be reporting a different graph rather than a different search.

**A link is walked in both directions, and the direction is kept.** A relation is
asserted one way round; a question is not. Refusing to walk backwards would make the
reachable set depend on which way an extractor happened to phrase a relation, and
forgetting which way it went would let a path claim the relation runs the other way.
So `Edge.forward` travels with every step of every walk.

**Order is total and comes from the data.** Neighbours are ordered by link id, which
is a content hash, so two runs over one corpus walk in the same order and a budget
cuts the same walk off at the same place. Nothing here is ordered by insertion, by
dictionary iteration or by a score this module cannot see.

**A budget that runs out is reported, never filled in.** `reach` and `walks` say what
they returned and whether they stopped early; what a caller does about a partial
result is the caller's business, and the one thing it must not do is present it as
complete.

Nothing here knows a type, a predicate or a schema: it takes the links it is given.
Which predicates are worth following is a decision above this file, expressed by
handing it fewer links.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import NamedTuple

from atlas.model import Frozen, Link

DEPTH = 2
"""How far a bounded reach goes by default. Two hops is the width of the pattern the
architectures are built around -- a thing, what was found about it, what that rests on
-- and a third hop typically doubles the neighbourhood without adding a relation a
reader would have followed on purpose."""

LIMIT = 200
"""How many nodes a bounded reach returns before it reports itself partial."""


class Edge(NamedTuple):
    """One link as it is traversed: where it leads, under what, and which way round."""

    other: str
    link_id: str
    predicate: str
    forward: bool


class Walk(Frozen):
    """One path through the graph: the nodes it visited and the links it crossed.

    The three tuples line up -- `len(links) == len(nodes) - 1` -- so the n-th link is
    how the walk got from the n-th node to the one after it, and `forward[n]` says
    whether that link was asserted in the direction the walk went. A renderer that
    drops `forward` turns "A was evaluated on B" into "B was evaluated on A", which is
    why it is part of the object and not recovered later.
    """

    nodes: tuple[str, ...]
    links: tuple[str, ...] = ()
    predicates: tuple[str, ...] = ()
    forward: tuple[bool, ...] = ()

    def extend(self, edge: Edge) -> Walk:
        """The walk that takes one more step along this edge."""
        return Walk(
            nodes=(*self.nodes, edge.other),
            links=(*self.links, edge.link_id),
            predicates=(*self.predicates, edge.predicate),
            forward=(*self.forward, edge.forward),
        )

    @property
    def length(self) -> int:
        """How many links the walk crosses; a walk that stayed where it started is 0."""
        return len(self.links)


class Reached(NamedTuple):
    """What a bounded reach found: the nodes, how each was arrived at, and whether it fit."""

    walks: dict[str, Walk]
    partial: bool

    def __len__(self) -> int:
        return len(self.walks)

    @property
    def nodes(self) -> tuple[str, ...]:
        """The nodes reached, nearest first and then by id, which is the visiting order."""
        return tuple(self.walks)


class Adjacency:
    """The links of a graph, indexed by the nodes they touch.

    Built once per question and read many times: every walk below, and every variant
    that does its own searching, goes through this rather than scanning the links.
    """

    def __init__(self, links: Iterable[Link]) -> None:
        self.links: dict[str, Link] = {link.id: link for link in links}
        self._edges: dict[str, list[Edge]] = {}
        for link in sorted(self.links.values(), key=lambda item: item.id):
            self._edges.setdefault(link.src, []).append(
                Edge(link.dst, link.id, link.predicate, True)
            )
            self._edges.setdefault(link.dst, []).append(
                Edge(link.src, link.id, link.predicate, False)
            )

    @classmethod
    def of(cls, links: Iterable[Link], follow: Iterable[str] = ()) -> Adjacency:
        """An adjacency over the links whose predicate is in `follow`; empty means all.

        Restricting the walk by dropping links rather than by testing a predicate at
        every step is what keeps this module free of any vocabulary: the caller knows
        which relations mean something for its question, and says so by handing over a
        smaller graph.
        """
        allowed = frozenset(follow)
        return cls(link for link in links if not allowed or link.predicate in allowed)

    def edges(
        self, node_id: str, *, forward: bool = True, backward: bool = True
    ) -> tuple[Edge, ...]:
        """The edges leaving a node, in link-id order, filtered by direction."""
        return tuple(
            edge
            for edge in self._edges.get(node_id, ())
            if (edge.forward and forward) or (not edge.forward and backward)
        )

    def degree(self, node_id: str) -> int:
        """How many link ends touch a node, counting a self-link twice."""
        return len(self._edges.get(node_id, ()))

    def nodes(self) -> tuple[str, ...]:
        """Every node id some link touches, in the order the links first touched them."""
        return tuple(self._edges)

    def __len__(self) -> int:
        return len(self.links)


def reach(
    adjacency: Adjacency,
    seeds: Iterable[str],
    *,
    depth: int = DEPTH,
    limit: int = LIMIT,
    forward: bool = True,
    backward: bool = True,
) -> Reached:
    """Every node within `depth` links of a seed, with the shortest walk that got there.

    Breadth first, so the walk kept for a node is one of the shortest ones and the
    budget is spent on the near neighbourhood before the far one. Seeds are reached at
    distance zero by a walk of no links, which is how a seed that no link touches
    still appears in what comes back.

    `partial` is true when the limit stopped the search with a frontier still to
    expand. It is the difference between "there is nothing further" and "we stopped
    looking", and every caller here passes it on rather than deciding it does not
    matter.
    """
    found: dict[str, Walk] = {}
    frontier: list[Walk] = []
    for seed in seeds:
        if seed not in found:
            found[seed] = Walk(nodes=(seed,))
            frontier.append(found[seed])
    for _hop in range(max(depth, 0)):
        following: list[Walk] = []
        for walk in frontier:
            for edge in adjacency.edges(walk.nodes[-1], forward=forward, backward=backward):
                if edge.other in found:
                    continue
                # The limit is a budget, and a budget that has run out has to be said
                # out loud: the caller is about to answer a question from this.
                if len(found) >= limit:
                    return Reached(found, True)
                found[edge.other] = walk.extend(edge)
                following.append(found[edge.other])
        frontier = following
    # A frontier left standing at the last hop is the depth doing its job, not a
    # budget failing: the caller asked for this far and got exactly this far.
    return Reached(found, False)


def walks(
    adjacency: Adjacency,
    source: str,
    target: str,
    *,
    depth: int = DEPTH,
    limit: int = LIMIT,
    forward: bool = True,
    backward: bool = True,
) -> tuple[Walk, ...]:
    """The simple paths from one node to another, shortest first, up to `limit` of them.

    Simple, meaning no node is visited twice: a walk that returns to where it has been
    explains nothing and multiplies without bound. Depth-first with an explicit stack
    and the neighbours in link-id order, so the same corpus yields the same paths in
    the same order however often it is asked.
    """
    if source == target:
        return (Walk(nodes=(source,)),)
    found: list[Walk] = []
    stack: list[Walk] = [Walk(nodes=(source,))]
    while stack and len(found) < limit:
        walk = stack.pop()
        if walk.length >= max(depth, 0):
            continue
        for edge in reversed(adjacency.edges(walk.nodes[-1], forward=forward, backward=backward)):
            if edge.other in walk.nodes:
                continue
            extended = walk.extend(edge)
            if edge.other == target:
                found.append(extended)
                if len(found) >= limit:
                    break
            else:
                stack.append(extended)
    return tuple(sorted(found, key=lambda walk: (walk.length, walk.links)))


def components(
    adjacency: Adjacency, among: Iterable[str] | None = None
) -> tuple[frozenset[str], ...]:
    """The connected components of the graph, or of the part of it `among` names.

    Ordered by size and then by their smallest id, so a report built over them is
    stable across runs. Used where a question is about the shape of the graph rather
    than about a particular node: which claims hang together, and which hang alone.
    """
    universe = set(adjacency.nodes()) if among is None else set(among)
    seen: set[str] = set()
    found: list[frozenset[str]] = []
    for start in sorted(universe):
        if start in seen:
            continue
        group = {start}
        queue = [start]
        while queue:
            for edge in adjacency.edges(queue.pop()):
                if edge.other in universe and edge.other not in group:
                    group.add(edge.other)
                    queue.append(edge.other)
        seen |= group
        found.append(frozenset(group))
    return tuple(sorted(found, key=lambda group: (-len(group), min(group))))


def weights(
    adjacency: Adjacency, by_predicate: Mapping[str, float] | None = None
) -> dict[str, float]:
    """A weight per link, from a table of weights per predicate; anything unnamed is 1.

    Diffusion and pruning both want to say that one kind of relation carries more of a
    question than another, and both want to say it in a configuration rather than in
    code. This turns that table into the per-link numbers those algorithms consume.
    """
    table = dict(by_predicate or {})
    return {link.id: float(table.get(link.predicate, 1.0)) for link in adjacency.links.values()}
