"""Letting relevance spread through the graph, and refusing to read the result as truth.

Some questions have no pattern. *"Which work connects these two ideas?"* names two things
and nothing about how they might be related, and a fixed walk from either of them finds
what is near it rather than what connects them. Diffusion answers that shape: start a
random walk at the nodes the question named, let it wander with a chance of restarting,
and see where it spends its time. Nodes reachable by several indirect routes accumulate
weight that no single path would have given them.

The result is a **ranking of places to look**, and three rules keep it from becoming
anything more.

**Direction does not become weight.** The relations that mean support and the ones that
mean dispute both carry the weight their predicate was given, because a diffusion needs
non-negative weights and a negative one is not a smaller positive one. Which side a
relation is on stays where it belongs -- in the graph, applied by the evidence closure --
so a heavily visited claim can turn out to be the disputed one, which happens and which
this arrangement makes visible rather than impossible.

**A score is not an answer.** What comes back with the ranking is the **connecting walks**:
how the diffusion got from a seed to each node it ranked. A node with a high score and no
walk to show for it is a hub, not a finding, and the walks are what let a reader tell the
difference.

**Hubs are the failure mode.** A relation that means almost nothing -- "mentioned in the
same paper" -- makes every well-connected node rank highly for every question. Per-
predicate weights are the control, `follow` is the blunter one, and the honest way to use
either is to look at the walks and see what the ranking was actually made of.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field

from atlas.model import Frozen
from atlas.steps import State, register
from atlas.steps.entail import mark
from atlas.steps.graph_expand import GraphExpandOptions, expand, widened
from atlas.steps.retrieve import Hit
from atlas.walk import Adjacency, Walk, walks, weights

DAMPING = 0.85
"""How much of the walk continues rather than restarting at a seed. A starting value for
a pilot, and not a claim about any published system's tuning: it is the number this
family of algorithms conventionally starts from, and it is meant to be measured."""

ROUNDS = 30
"""Power iterations before the ranking is taken as it stands. Enough to settle on a graph
of this size; a cap rather than a convergence criterion, and it says so."""


class Ranked(Frozen):
    """One node the diffusion reached, what it scored, and how the walk got there."""

    node_id: str
    score: float
    walk: Walk | None = None

    @property
    def explained(self) -> bool:
        """Whether there is a route from a seed to show for the score."""
        return self.walk is not None and self.walk.length > 0


class DiffuseOptions(Frozen):
    """How the walk behaves, how far it may wander, and what each relation is worth.

    `weights` is per predicate and is the control for hub bias: a relation that means
    almost nothing gets a small number, and the ranking stops being about how
    well-connected a node happens to be. Anything unnamed is worth one.
    """

    damping: float = Field(DAMPING, gt=0.0, lt=1.0)
    rounds: int = Field(ROUNDS, ge=1)
    limit: int = Field(12, gt=0, description="Nodes kept as roots for the evidence closure")
    depth: int = Field(3, ge=1, description="How long a connecting walk may be")
    weights: dict[str, float] = Field(default_factory=dict)
    expand: GraphExpandOptions = GraphExpandOptions()


@register("diffuse", requires=("store", "hits"), produces=("bundle", "ranked"),
          options=DiffuseOptions)
def diffuse(state: State, options: DiffuseOptions) -> State:
    """Spread relevance from the ranked nodes, and package what it reached with its routes."""
    store = state["store"]
    hits: tuple[Hit, ...] = state["hits"]
    schema = state.get("schema")
    walked = widened(options.expand, schema) if schema is not None else options.expand
    derived = tuple(state.get("derived", ()))
    adjacency = Adjacency.of([*store.links(), *derived], walked.follow)
    seeds = _seeds(hits)
    scores = pagerank(adjacency, seeds, damping=options.damping, rounds=options.rounds,
                      by_predicate=options.weights)
    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:options.limit]
    ranked = tuple(
        Ranked(node_id=node_id, score=round(score, 6),
               walk=_route(adjacency, seeds, node_id, options.depth))
        for node_id, score in ordered
    )
    bundle = expand(
        store,
        [one.node_id for one in ranked],
        walked,
        reasons={
            one.node_id: (f"diffusion {one.score:.4f}"
                          + ("" if one.explained else ", with no route from a seed"))
            for one in ranked
        },
        snapshot=getattr(state.get("schema"), "version", "") or "",
        method="diffuse",
        adjacency=adjacency,
    )
    return {"bundle": mark(bundle, derived, state.get("typings", ())), "ranked": ranked}


def pagerank(
    adjacency: Adjacency,
    seeds: Mapping[str, float],
    *,
    damping: float = DAMPING,
    rounds: int = ROUNDS,
    by_predicate: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Personalised PageRank over the adjacency, restarting at the seed distribution.

    Power iteration, fixed number of rounds, weights per edge from the table of weights
    per predicate. Every edge is walked in both directions, as everywhere in this
    library, because a relation is asserted one way round and a question is not.

    Weights are non-negative by construction: a table naming a negative number would be
    asking the walk to spend negative time somewhere, which is not a thing. That is why
    which side a relation is on is not expressed here.
    """
    nodes = sorted(adjacency.nodes())
    if not nodes or not seeds:
        return {}
    per_link = weights(adjacency, by_predicate)
    start = _normalised({node_id: seeds.get(node_id, 0.0) for node_id in nodes})
    scores = dict(start)
    for _round in range(rounds):
        spread = dict.fromkeys(nodes, 0.0)
        for node_id in nodes:
            edges = adjacency.edges(node_id)
            out = sum(max(per_link.get(edge.link_id, 1.0), 0.0) for edge in edges)
            if out <= 0:
                # A node with nowhere to go returns its weight to the seeds rather than
                # losing it, which is what keeps the distribution summing to one.
                for seed, share in start.items():
                    spread[seed] += scores[node_id] * share
                continue
            for edge in edges:
                share = max(per_link.get(edge.link_id, 1.0), 0.0) / out
                spread[edge.other] += scores[node_id] * share
        scores = {
            node_id: (1 - damping) * start[node_id] + damping * spread[node_id]
            for node_id in nodes
        }
    return scores


def _route(
    adjacency: Adjacency, seeds: Mapping[str, float], node_id: str, depth: int
) -> Walk | None:
    """The shortest walk from any seed to this node, which is what explains its score."""
    for seed in sorted(seeds, key=lambda one: (-seeds[one], one)):
        if seed == node_id:
            continue
        found = walks(adjacency, seed, node_id, depth=depth, limit=1)
        if found:
            return found[0]
    return None


def _seeds(hits: tuple[Hit, ...]) -> dict[str, float]:
    """The starting distribution: where the question said to begin, in proportion."""
    return _normalised({hit.node.id: max(hit.score, 0.0) for hit in hits})


def _normalised(values: Mapping[str, float]) -> dict[str, float]:
    """The same numbers summing to one, or spread evenly if they sum to nothing."""
    total = sum(values.values())
    if total <= 0:
        share = 1 / len(values) if values else 0.0
        return dict.fromkeys(values, share)
    return {key: value / total for key, value in values.items()}
