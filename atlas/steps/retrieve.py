"""Ranking the nodes of a store against a question, over the index built beside it.

The default scoring is deliberately simple, and says so here so that nobody reads a
relevance model into it: a node scores by how many distinct terms of the question it
contains, divided by the square root of its own length. That is term overlap with a
length normalisation and nothing else -- no idf, no phrases, no field weighting, no
vectors, no lemmatisation -- which is the right amount of machinery for hundreds of
documents and is honest about its limit: a question phrased in words the text does not
use finds nothing, and in an inflected language the wrong form of a word is such a
question. It works the same in every language the folding covers, because the terms
come from `atlas.text` and not from a rule written here.

The ranking a demo wants is not the ranking every consumer wants, and the answer to
that is the one the library already has: write a step and name it in the configuration
instead of this one. `overlap` is public so such a step can keep the scoring and change
the rest, or keep the rest and change the scoring -- either way in its own module,
without a second registry inside this one to be configured through.
"""

from __future__ import annotations

import math

from atlas.model import Frozen, Node
from atlas.steps import State, register
from atlas.steps.index_nodes import Index
from atlas.text import tokenise

LIMIT = 8
"""How many hits a question gets by default: enough to answer from, few enough to put in
one prompt without the evidence being crowded out by near-misses."""

def overlap(index: Index, question: str) -> dict[str, float]:
    """Distinct terms shared with the question, over the square root of the node's length.

    The overlap is over distinct terms, so repeating a word in the question does not
    weigh it twice, and a node repeating it does not outrank a shorter node that says it
    once. The normalisation is what stops a long node from winning by breadth alone.
    """
    shared: dict[str, float] = {}
    for term in set(tokenise(question)):
        for node_id in index.postings.get(term, {}):
            shared[node_id] = shared.get(node_id, 0.0) + 1.0
    return {
        node_id: count / math.sqrt(max(index.lengths.get(node_id, 1), 1))
        for node_id, count in shared.items()
    }


class Hit(Frozen):
    """One ranked node and the score it was ranked by.

    Nothing else: the node carries where it was read from, what it stands on and the
    reference an answer cites it by, and a second copy of any of those would be a
    second thing to keep true.
    """

    node: Node
    score: float


class RetrieveOptions(Frozen):
    """What a configuration may write under `retrieve`, and the only place its default lives.

    The model is the declaration: a key it does not name is refused when the file is read,
    with this step named, rather than being taken for an option and silently dropped.
    """

    limit: int = LIMIT


@register("retrieve", requires=("store", "index", "question"), produces=("hits",),
          options=RetrieveOptions)
def retrieve(state: State, options: RetrieveOptions) -> State:
    """Rank the indexed nodes against the question the run carries, best first."""
    scores = overlap(state["index"], state["question"])
    # Ties break on the node id, so two runs over one corpus rank identically.
    ordered = sorted(scores.items(), key=lambda scored: (-scored[1], scored[0]))[:options.limit]
    # The index outlives the node it indexed: a superseded node is no longer projected,
    # and a hit on it would quote evidence the store no longer claims. The store is the
    # authority on what is current, so the ranking is resolved through it and not around it.
    nodes = state["store"].get_nodes([node_id for node_id, _ in ordered])
    # No count beside the hits: `counts` measures anything that knows its own length, so
    # a second integer saying how many there are would be the same number written twice.
    return {"hits": tuple(Hit(node=node, score=scores[node.id]) for node in nodes)}
