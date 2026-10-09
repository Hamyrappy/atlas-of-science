"""Choosing which kind of question this is, and seeding the walk accordingly.

One retriever does not answer three kinds of question well. *What did this paper find?*
wants the neighbourhood of one thing. *Which of these were compared under the same
protocol?* wants a longer walk across typed relations. *How has this field moved?* wants
the whole of a region, and answering it from the top-ranked passages produces a summary
of whatever the ranking liked.

So the route is chosen first, and what changes with it is **which seeds the walk starts
from and how many** -- not whether the graph is walked, which is never in question. The
walk that follows is the same `graph_expand` for every route, which is what keeps one
evidence package and one answering step across all three.

**The router is deterministic first.** Markers are matched against the question, and the
model is asked only where nothing matched and a client is available. That is the cheap
ordering and also the honest one: a run can see why a question went where it went, and
`route_reason` says which marker or which model call decided it. The markers are the
configuration's, because they are words of a language and this package holds none: with
nothing configured, everything goes to the default route.

**An overview route does not take a top-k.** It takes *every* member of the matched
communities, up to a stated cap, because a question about how much of a field does
something is a question about a set and answering it from the best eight is answering a
different question. When the cap binds, the run says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from atlas.model import Frozen
from atlas.steps import State, register
from atlas.steps.index_nodes import Index
from atlas.steps.retrieve import LIMIT, Hit, overlap
from atlas.text import tokenise

if TYPE_CHECKING:
    from atlas.llm import ChatClient

FACT = "fact"
OVERVIEW = "overview"

PROMPT = """Say which kind of question this is.

Kinds:
{kinds}

Answer with {{"route": "<one of the kinds above>"}} and nothing else.

Question: {question}
"""


class RouteOptions(Frozen):
    """The routes on offer, the words that choose each one, and whether to ask the model.

    `markers` maps a route to the words that send a question to it, in the language of
    the corpus. `default` is where a question goes when nothing matched and no model was
    asked, and it must be one of the routes -- a router with a default nothing serves is
    a router that silently drops questions.
    """

    routes: tuple[str, ...] = Field(default=(FACT, OVERVIEW), min_length=1)
    markers: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    default: str = FACT
    ask_model: bool = False


@register("route", requires=("question",), produces=("route", "route_reason"),
          options=RouteOptions)
def route(state: State, options: RouteOptions) -> State:
    """Pick the route for this question, deterministically where possible."""
    question = state["question"]
    terms = set(tokenise(question))
    lowered = question.casefold()
    for name in options.routes:
        for marker in options.markers.get(name, ()):
            folded = marker.casefold()
            if folded in terms or folded in lowered:
                return {"route": name, "route_reason": f"matched marker {marker!r}"}
    client: ChatClient | None = state.get("client") if options.ask_model else None
    if client is not None:
        chosen = _asked(client, question, options)
        if chosen is not None:
            return {"route": chosen, "route_reason": "chosen by the model"}
    return {"route": options.default, "route_reason": "nothing matched; the default route"}


class RetrieveRoutedOptions(Frozen):
    """How each route seeds the walk: a few ranked nodes, or a whole region of the graph."""

    overview: str = Field(OVERVIEW, description="The route that takes whole communities")
    limit: int = Field(LIMIT, gt=0)
    communities: int = Field(2, ge=1, description="How many communities an overview takes")
    cap: int = Field(300, gt=0, description="Most nodes an overview may seed from")


@register("retrieve_routed", requires=("store", "index", "question", "route"),
          produces=("hits", "route_capped"), options=RetrieveRoutedOptions)
def retrieve_routed(state: State, options: RetrieveRoutedOptions) -> State:
    """Seed the walk the way this route asks: ranked nodes, or the members of a region."""
    index: Index = state["index"]
    question: str = state["question"]
    scores = overlap(index, question)
    if state["route"] != options.overview:
        ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:options.limit]
        nodes = state["store"].get_nodes([node_id for node_id, _ in ordered])
        return {"hits": tuple(Hit(node=node, score=scores[node.id], via=state["route"])
                              for node in nodes),
                "route_capped": False}

    chosen = _regions(state.get("communities", ()), scores, options.communities)
    members = [node_id for community in chosen for node_id in community.members]
    capped = len(members) > options.cap
    nodes = state["store"].get_nodes(members[:options.cap])
    return {
        "hits": tuple(
            Hit(node=node, score=scores.get(node.id, 0.0), via=options.overview)
            for node in nodes
        ),
        # A question about how much of a field does something is a question about a set,
        # so the run says when it did not get the whole set.
        "route_capped": capped,
    }


def _regions(found, scores: dict[str, float], how_many: int):
    """The communities whose members the ranking liked best, whole rather than sampled."""
    ranked = sorted(
        found,
        key=lambda community: (
            -sum(scores.get(node_id, 0.0) for node_id in community.members), community.id
        ),
    )
    return [community for community in ranked[:how_many]
            if any(scores.get(node_id) for node_id in community.members)]


def _asked(client: ChatClient, question: str, options: RouteOptions) -> str | None:
    """What the model calls this question, if it names one of the routes on offer."""
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["route"],
        "properties": {"route": {"type": "string", "enum": list(options.routes)}},
    }
    body, _reply = client.complete_json(
        PROMPT.format(kinds="\n".join(f"- {name}" for name in options.routes),
                      question=question),
        schema,
    )
    chosen = body.get("route")
    return chosen if chosen in options.routes else None
