"""Partitioning the graph into communities, and writing a report that is never evidence.

A question about a whole field -- what changed, what is being worked on, where the
weight of the work sits -- cannot be answered from a neighbourhood of a few nodes, and
answering it by ranking passages produces a summary of whatever the ranking happened to
like. The shape that answers it is a partition: groups of things that are related to
each other more than to the rest, each with a report of what is in it.

Two decisions define this module.

**A report is derived, and can never be cited as evidence.** `Community.report` is a
sentence built from the members' own labels, and it is not a `Node`: it has no span, it
is never asserted, and `graph_answer` only accepts citations of nodes that are in the
package. So a generator cannot cite the summary in place of the studies it summarises --
not because it is asked not to, but because the reference does not resolve. A report that
restates an existing study is not a second study, and this is where that is enforced.

**A report is rebuilt, never invalidated.** Communities are computed per question from
the store's current projection. When a study is superseded, it stops being projected and
the next report simply does not contain it; there is no cache to remember to clear. That
is the whole of the invalidation story, and it is short because the store is append-only
and the projection is a function of it.

The partition is **greedy modularity agglomeration**: every node starts in its own
community, and the pair of connected communities whose merge raises modularity most is
merged, until no merge would raise it. It needs no parameter for how many communities
there should be, it is deterministic once ties are broken on community id, and -- unlike
label propagation, which was tried here first -- it does not collapse a graph of a few
dozen nodes into one community. Two cliques joined by a single edge come apart, which is
the least a partition has to do to be worth computing.

It is a greedy approximation and says so: the merge order is locally optimal and the
result is not the best partition of the graph. It is a partition two runs over one
corpus agree on, which is the property a report has to have.
"""

from __future__ import annotations

from pydantic import Field

from atlas.model import Frozen, Schema
from atlas.steps import State, register
from atlas.store import Store
from atlas.walk import Adjacency

ROUNDS = 8
"""A safety rail on how many merges are attempted, as a multiple of the node count. The
stopping rule is the modularity -- no merge that raises it, no merge -- and this is only
there so that a pathological graph cannot spin."""


class Community(Frozen):
    """One group of the partition: what is in it, what kinds, and what it comes to.

    `report` is derived text. It is deliberately not a node and deliberately carries no
    span: nothing in this library lets a reader cite it, because a summary of studies is
    not a study.
    """

    id: str
    members: tuple[str, ...]
    kinds: tuple[str, ...] = ()
    report: str = ""
    coverage: float = Field(
        default=0.0, description="Share of the projected nodes this community holds"
    )

    def __len__(self) -> int:
        return len(self.members)


class CommunitiesOptions(Frozen):
    """Which relations hold a community together, and how small one may be."""

    follow: tuple[str, ...] = ()
    min_size: int = Field(2, ge=1)
    rounds: int = Field(ROUNDS, ge=1)
    members_in_report: int = Field(5, ge=1)


@register("communities", requires=("store",), produces=("communities",),
          options=CommunitiesOptions)
def communities(state: State, options: CommunitiesOptions) -> State:
    """Partition the projected graph and write a derived report for each group."""
    store: Store = state["store"]
    schema: Schema | None = state.get("schema")
    nodes = {node.id: node for node in store.nodes()}
    adjacency = Adjacency.of(store.links(), options.follow)
    labels = partition(adjacency, options.rounds)
    grouped: dict[str, list[str]] = {}
    for node_id, label in sorted(labels.items()):
        if node_id in nodes:
            grouped.setdefault(label, []).append(node_id)
    total = max(len(nodes), 1)
    found = tuple(
        _community(index, members, nodes, schema, total, options)
        for index, (_label, members) in enumerate(
            sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))
        )
        if len(members) >= options.min_size
    )
    return {"communities": found}


def partition(adjacency: Adjacency, rounds: int = ROUNDS) -> dict[str, str]:
    """Greedy modularity agglomeration over the adjacency, with every order fixed.

    Modularity compares the edges inside a community with the edges there would be if
    the same degrees were wired at random; the merge that raises it most is taken, and
    the process stops when no merge would. `rounds` bounds the number of merges as a
    safety rail, not as a tuning knob -- the stopping rule is the modularity, and a
    graph that wants more merges than the cap allows reports the partition it reached.

    Returns the community label of every node the adjacency touches.
    """
    nodes = sorted(adjacency.nodes())
    labels = {node_id: node_id for node_id in nodes}
    edges = list(adjacency.links.values())
    total = len(edges)
    if not total:
        return labels
    degrees = {node_id: adjacency.degree(node_id) for node_id in nodes}
    members: dict[str, set[str]] = {node_id: {node_id} for node_id in nodes}

    for _merge in range(max(rounds, 1) * max(len(nodes), 1)):
        between = _between(edges, labels)
        if not between:
            break
        weight = {label: sum(degrees[one] for one in group) for label, group in members.items()}
        best, gain = None, 0.0
        for (one, other), shared in sorted(between.items()):
            # The standard gain for merging two communities of a weighted graph, with
            # every edge weighing one: what is between them, less what chance would put
            # there given their degrees.
            change = shared / total - (weight[one] * weight[other]) / (2 * total**2)
            if change > gain:
                best, gain = (one, other), change
        if best is None:
            break
        keep, absorbed = best
        for node_id in members.pop(absorbed):
            labels[node_id] = keep
            members[keep].add(node_id)
    return labels


def _between(edges: list, labels: dict[str, str]) -> dict[tuple[str, str], int]:
    """How many edges run between each pair of distinct communities."""
    found: dict[tuple[str, str], int] = {}
    for edge in edges:
        here, there = labels.get(edge.src), labels.get(edge.dst)
        if here is None or there is None or here == there:
            continue
        pair = (here, there) if here < there else (there, here)
        found[pair] = found.get(pair, 0) + 1
    return found


def _community(
    index: int,
    members: list[str],
    nodes: dict,
    schema: Schema | None,
    total: int,
    options: CommunitiesOptions,
) -> Community:
    """One group with its derived report, which is prose about nodes and not a node."""
    held = [nodes[node_id] for node_id in members]
    labelled = [schema.label_of(node) if schema else node.type for node in held]
    kinds = tuple(sorted({node.type for node in held}))
    shown = ", ".join(labelled[:options.members_in_report])
    more = f" and {len(labelled) - options.members_in_report} more" if (
        len(labelled) > options.members_in_report
    ) else ""
    return Community(
        id=f"c{index:03d}",
        members=tuple(members),
        kinds=kinds,
        report=f"{len(members)} things of {len(kinds)} kind(s): {shown}{more}.",
        coverage=round(len(members) / total, 4),
    )
