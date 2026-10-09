"""Returning the chains that explain a connection, and keeping the one that argues against it.

A graph search that returns everything within two hops returns thirty restatements of one
result and buries the chain a reader actually wanted. What explains a connection is an
**ordered path** -- this method was used for that task, evaluated by that measure, which
produced that number -- and a handful of those is worth more than a neighbourhood.

So the search enumerates bounded simple paths between the nodes the question named,
scores them by a flow that decays with each hop, and prunes. Then the evidence closure
runs, as everywhere.

Two rules decide whether the pruning is safe.

**Redundancy is judged by content, not by text.** Two paths crossing the same relations
between the same things are one path however differently they read; two paths with the
same shape over different studies are two. The signature is the sequence of predicates
with the nodes between them, which is what "the same explanation" actually means here.

**A counter-path is never pruned.** A path that crosses a relation the configuration
names as opposing is kept whatever it scored. This is the rule the module exists to
state: pruning optimises for the chain that explains the connection, and the chain that
argues against it is rare by nature and scores badly by construction. Losing it would
make a pruned search systematically more confident than an unpruned one, which is the
exact opposite of what a smaller context is supposed to buy.

The flow model is a decay per hop times the weight of each relation crossed. It is not
PathRAG's published algorithm and does not claim to be; it is a monotone scoring that
prefers short, heavily-weighted chains, and the part that matters -- what may be thrown
away -- is above.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import Field

from atlas.model import Frozen
from atlas.steps import State, register
from atlas.steps.entail import mark
from atlas.steps.graph_expand import GraphExpandOptions, expand, widened
from atlas.steps.retrieve import Hit
from atlas.walk import Adjacency, Walk, walks, weights

DECAY = 0.8
"""What a hop costs, multiplicatively. Below one so that a short chain outranks a long
one saying the same thing; not so far below that a three-hop explanation is unreachable."""


class Path(Frozen):
    """One ordered chain, what it scored, and why it was kept."""

    walk: Walk
    score: float
    reason: str = ""

    @property
    def signature(self) -> tuple[str, ...]:
        """What makes two paths the same explanation: the things crossed, in order.

        Nodes and predicates interleaved. Two chains over different studies have
        different signatures however alike they read, and two readings of one chain have
        the same signature however differently.
        """
        parts: list[str] = [self.walk.nodes[0]]
        for index, predicate in enumerate(self.walk.predicates):
            parts += [predicate, self.walk.nodes[index + 1]]
        return tuple(parts)


class SelectPathsOptions(Frozen):
    """How long a chain may be, how many survive, what each hop costs, and what may not be cut."""

    depth: int = Field(4, ge=1)
    keep: int = Field(8, gt=0, description="Paths kept after pruning, counter-paths aside")
    candidates: int = Field(60, gt=0, description="Paths enumerated per pair before scoring")
    decay: float = Field(DECAY, gt=0.0, le=1.0)
    weights: dict[str, float] = Field(default_factory=dict)
    expand: GraphExpandOptions = GraphExpandOptions()


@register("select_paths", requires=("store", "hits"), produces=("bundle", "paths"),
          options=SelectPathsOptions)
def select_paths(state: State, options: SelectPathsOptions) -> State:
    """Find the chains between what the question named, prune them, and package what is left."""
    store = state["store"]
    hits: tuple[Hit, ...] = state["hits"]
    schema = state.get("schema")
    walked = widened(options.expand, schema) if schema is not None else options.expand
    derived = tuple(state.get("derived", ()))
    adjacency = Adjacency.of([*store.links(), *derived], walked.follow)
    roots = tuple(dict.fromkeys(hit.node.id for hit in hits))
    found = enumerate_paths(adjacency, roots, options)
    kept = prune(found, options.keep, walked.opposes, adjacency)
    nodes = tuple(dict.fromkeys(
        [node_id for path in kept for node_id in path.walk.nodes] or list(roots)
    ))
    bundle = expand(
        store,
        nodes,
        walked,
        reasons={path.walk.nodes[-1]: path.reason for path in kept},
        snapshot=getattr(state.get("schema"), "version", "") or "",
        method="select_paths",
        adjacency=adjacency,
    )
    return {"bundle": mark(bundle, derived, state.get("typings", ())), "paths": kept}


def enumerate_paths(
    adjacency: Adjacency, roots: Iterable[str], options: SelectPathsOptions
) -> tuple[Path, ...]:
    """Every bounded simple chain between two of the named nodes, scored by its flow."""
    named = tuple(roots)
    per_link = weights(adjacency, options.weights)
    found: list[Path] = []
    for index, source in enumerate(named):
        for target in named[index + 1:]:
            for walk in walks(adjacency, source, target, depth=options.depth,
                              limit=options.candidates):
                found.append(Path(walk=walk, score=flow(walk, per_link, options.decay)))
    return tuple(sorted(found, key=lambda path: (-path.score, path.signature)))


def flow(walk: Walk, per_link: Mapping[str, float], decay: float) -> float:
    """What survives of a unit of attention sent down this chain.

    The weight of each relation crossed, times a decay per hop. Monotone in length, so a
    short chain beats a long one that says the same thing, and monotone in weight, so a
    chain through a relation nobody thinks means much does not win by being short.
    """
    carried = 1.0
    for link_id in walk.links:
        carried *= max(per_link.get(link_id, 1.0), 0.0) * decay
    return round(carried, 6)


def prune(
    found: Iterable[Path], keep: int, opposes: Iterable[str], adjacency: Adjacency
) -> tuple[Path, ...]:
    """Drop what repeats, keep the best of the rest, and keep every counter-path.

    The order is deliberate. Deduplication by signature happens first, so a counter-path
    is not kept twice. Then the budget takes the best; then the counter-paths that the
    budget dropped are put back, each carrying the reason it survived -- because a
    reader who sees a rare objection in a pruned answer should be able to tell that it
    was kept on purpose rather than by luck.
    """
    against = frozenset(opposes)
    seen: set[tuple[str, ...]] = set()
    unique: list[Path] = []
    for path in found:
        if path.signature in seen:
            continue
        seen.add(path.signature)
        unique.append(path)
    kept = [
        path.model_copy(update={"reason": f"flow {path.score:.4f}"}) for path in unique[:keep]
    ]
    held = {path.signature for path in kept}
    kept += [
        path.model_copy(update={"reason": f"flow {path.score:.4f}, kept as a counter-path"})
        for path in unique[keep:]
        if path.signature not in held and _argues_against(path, against, adjacency)
    ]
    return tuple(kept)


def _argues_against(path: Path, against: frozenset[str], adjacency: Adjacency) -> bool:
    """Whether this chain crosses a relation the configuration named as opposing."""
    return bool(against) and any(
        adjacency.links[link_id].predicate in against for link_id in path.walk.links
    )
