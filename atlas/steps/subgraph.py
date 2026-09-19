"""Choosing a small connected region of the graph that is worth its context budget.

A question that does not translate into a pattern -- *"what connects these two lines of
work?"* -- cannot be answered by a walk of fixed depth from ranked seeds. Two hops from
a strong seed reaches a hundred nodes of which four matter; two hops from a weak one
reaches nothing. What the question wants is a **small connected region** holding the
valuable nodes and as little else as possible.

That is the prize-collecting Steiner tree problem: each node carries a prize, each edge
a cost, and the object is a connected subgraph maximising prizes minus costs. It is
NP-hard, and what is implemented here is not an approximation algorithm with a bound. It
is a **greedy growth**: start from the best-prized node, repeatedly attach whichever
unselected node has the best prize for the cost of reaching it, stop when nothing pays.
That is said plainly because a module named after PCST and quietly doing something else
would make every comparison against it meaningless.

Three rules matter more than the selection quality.

**An n-ary node is taken whole or not at all.** A study relates a method, a dataset, a
measure and a number, and it means nothing in pieces: a selector that kept the method
and the number and dropped the dataset has produced a compact subgraph asserting
something nobody claimed. Types named in `whole` bring their `parts` relations with them.

**The evidence closure is not optional.** Once the region is chosen it goes through the
same `expand` as everything else, which pulls in the objections whatever the budget did.

**When the budget binds, take fewer things with complete grounds.** Not more things
without them. `trim` drops the lowest-prized roots and reselects rather than truncating
the closure, because a package of ten results with no evidence is worse than three with
it.

Nothing here is learned. A trained selector would replace `prize` and nothing else, which
is why the prizes arrive as an argument: the comparison between a learned relevance and
a ranked one is then one substitution, and until there is a graph with question-evidence
pairs to train on, the ranked one is what runs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import Field

from atlas.model import Frozen
from atlas.steps import State, register
from atlas.steps.graph_expand import Bundle, GraphExpandOptions, expand
from atlas.steps.retrieve import Hit
from atlas.walk import Adjacency

COST = 1.0
"""What crossing one relation costs by default, against prizes normalised to at most 1.
An edge has to be worth a node of middling relevance, or a region grows to the corpus."""


class Selection(Frozen):
    """The region chosen, what it was worth, and whether the budget cut it short."""

    nodes: tuple[str, ...] = ()
    prize: float = 0.0
    cost: float = 0.0
    trimmed: int = Field(default=0, description="Roots dropped to fit the closure in budget")

    @property
    def value(self) -> float:
        """Prizes collected less the cost of staying connected."""
        return round(self.prize - self.cost, 6)

    def __len__(self) -> int:
        return len(self.nodes)


class SubgraphOptions(Frozen):
    """How much a relation costs, how large a region may be, and what may not be split."""

    cost: float = Field(COST, ge=0.0)
    limit: int = Field(30, gt=0, description="Nodes the region may hold before it stops growing")
    whole: tuple[str, ...] = Field(
        default=(), description="Types that bring their parts with them, or are left out"
    )
    parts: tuple[str, ...] = Field(
        default=(), description="Relations reaching the parts of such a type"
    )
    expand: GraphExpandOptions = GraphExpandOptions()


@register("select_subgraph", requires=("store", "hits"), produces=("bundle", "selection"),
          options=SubgraphOptions)
def select_subgraph(state: State, options: SubgraphOptions) -> State:
    """Grow a small connected region around the best-ranked nodes and package it."""
    store = state["store"]
    hits: tuple[Hit, ...] = state["hits"]
    links = store.links()
    adjacency = Adjacency.of(links, options.expand.follow)
    whole = _whole(store, adjacency, options)
    prizes = _prizes(hits)

    selection = grow(adjacency, prizes, options, whole)
    bundle = expand(
        store,
        selection.nodes,
        options.expand,
        reasons={
            node_id: f"selected, prize {prizes.get(node_id, 0.0):.3f}"
            for node_id in selection.nodes
        },
        snapshot=getattr(state.get("schema"), "version", "") or "",
        method="select_subgraph",
        adjacency=adjacency,
    )
    bundle, dropped = trim(store, bundle, prizes, options, adjacency)
    return {"bundle": bundle, "selection": selection.model_copy(update={"trimmed": dropped})}


def grow(
    adjacency: Adjacency,
    prizes: Mapping[str, float],
    options: SubgraphOptions,
    whole: Mapping[str, tuple[str, ...]],
) -> Selection:
    """Greedy prize-collecting growth from the best-prized node.

    Deterministic: candidates are ordered by gain and then by id, so two runs over one
    corpus select the same region and a budget cuts it at the same place. A node that
    brings parts with it is scored with them, because taking it means taking them.
    """
    if not prizes:
        return Selection()
    first = max(sorted(prizes), key=lambda node_id: prizes[node_id])
    chosen = {first, *whole.get(first, ())}
    collected = sum(prizes.get(node_id, 0.0) for node_id in chosen)
    spent = 0.0
    while len(chosen) < options.limit:
        best, gain, brings = None, 0.0, ()
        for node_id in sorted(chosen):
            for edge in adjacency.edges(node_id):
                if edge.other in chosen:
                    continue
                attached = (edge.other, *whole.get(edge.other, ()))
                worth = sum(prizes.get(one, 0.0) for one in attached if one not in chosen)
                pays = worth - options.cost
                if pays > gain:
                    best, gain, brings = edge.other, pays, attached
        if best is None:
            break
        for one in brings:
            if one not in chosen:
                chosen.add(one)
                collected += prizes.get(one, 0.0)
        spent += options.cost
    return Selection(nodes=tuple(sorted(chosen)), prize=round(collected, 6), cost=spent)


def trim(
    store,
    bundle: Bundle,
    prizes: Mapping[str, float],
    options: SubgraphOptions,
    adjacency: Adjacency,
) -> tuple[Bundle, int]:
    """Drop the least valuable roots until the closed package fits, and say how many.

    Fewer results with complete grounds, never more results without them. The closure is
    what may not be cut, so what gives is the number of things asked about -- and the
    count of what was dropped travels back, because a package that quietly answered a
    smaller question would be the worst outcome here.
    """
    dropped = 0
    roots = list(bundle.roots)
    while len(bundle.nodes) > options.expand.limit and len(roots) > 1:
        roots.sort(key=lambda node_id: (prizes.get(node_id, 0.0), node_id))
        roots.pop(0)
        dropped += 1
        bundle = expand(
            store,
            roots,
            options.expand,
            reasons={one: f"selected, prize {prizes.get(one, 0.0):.3f}" for one in roots},
            snapshot=bundle.snapshot,
            method=bundle.method,
            adjacency=adjacency,
        )
    return bundle, dropped


def _prizes(hits: Iterable[Hit]) -> dict[str, float]:
    """Relevance as a prize per node, normalised so that the edge cost means something.

    A learned selector replaces exactly this function and nothing else, which is the
    seam the architecture is built around: the comparison between a learned relevance
    and a ranked one is one substitution, not a second retrieval stack.
    """
    held = tuple(hits)
    if not held:
        return {}
    top = max(hit.score for hit in held) or 1.0
    return {hit.node.id: hit.score / top for hit in held}


def _whole(store, adjacency: Adjacency, options: SubgraphOptions) -> dict[str, tuple[str, ...]]:
    """For each node that may not be split, the parts that have to come with it."""
    if not options.whole or not options.parts:
        return {}
    kinds = set(options.whole)
    found: dict[str, tuple[str, ...]] = {}
    for node in store.nodes():
        if node.type not in kinds:
            continue
        parts = tuple(sorted(
            edge.other for edge in adjacency.edges(node.id, backward=False)
            if edge.predicate in options.parts
        ))
        if parts:
            found[node.id] = parts
    return found
