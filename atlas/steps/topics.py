"""The map layer, and the two-level search that uses it without confusing it with a class.

A corpus has three different identities running through it and conflating any two of
them is the classic way an induced ontology goes wrong:

- a **mention** is a place in a text;
- a **topic** is a group of things the corpus discusses together;
- a **class** is a kind of thing.

This module builds the middle one and keeps it in its place. A topic is derived from
the graph -- the connected groups of what is actually related -- labelled from the terms
its members share, and rebuilt whenever the graph changes. It is never asserted, never
given an IRI and never promoted: `Topic.mixed` says out loud when a group holds things
of several kinds, which is the case where a topic looks most like a class and is least
like one. A dense group of a method, a task and a benchmark is a subject area. It is not
a type, and the negative example is the whole reason this file says so in a field rather
than in a comment.

`retrieve_dual` is what the map is for. A question is matched against two things at
once: the nodes, by the terms they use, and the topics, by the terms their members
share. The topic branch reaches nodes that share no word with the question -- which is
the failure of pure term overlap -- and every hit records which branch found it, so a
node reached only through a topic can be told apart from one the question actually
named. Topical closeness is a reason to look, never evidence of a relation, and the
walk that follows has to earn that separately.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pydantic import Field

from atlas.model import Frozen, Node, Schema
from atlas.steps import State, register
from atlas.steps.index_nodes import Index
from atlas.steps.retrieve import LIMIT, Hit, overlap
from atlas.store import Store
from atlas.text import tokenise
from atlas.walk import Adjacency, components

TERMS = 5
"""How many shared terms a topic is labelled by. Enough to recognise, few enough to read."""


class Topic(Frozen):
    """One group of things the corpus discusses together, with what they have in common."""

    id: str
    label: str
    terms: tuple[str, ...] = ()
    members: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()

    @property
    def mixed(self) -> bool:
        """Whether the group holds things of several kinds, and is therefore not a class."""
        return len(self.kinds) > 1

    def __len__(self) -> int:
        return len(self.members)


class TopicsOptions(Frozen):
    """Which relations tie things into a topic, and how small a topic may be.

    `follow` empty means every relation: a first map of an unfamiliar corpus. Naming a
    few is how a run says that only some relations mean "discussed together" -- on a
    pack where everything hangs off one hub type, following all of them produces one
    topic containing the corpus, which is a true and useless map.
    """

    follow: tuple[str, ...] = ()
    min_size: int = Field(2, ge=1)
    terms: int = Field(TERMS, ge=1)


@register("topics", requires=("store",), produces=("topics", "mixed_topics"),
          options=TopicsOptions)
def topics(state: State, options: TopicsOptions) -> State:
    """Build the map: the connected groups of the graph, labelled by what their members share."""
    store: Store = state["store"]
    schema: Schema | None = state.get("schema")
    nodes = {node.id: node for node in store.nodes()}
    adjacency = Adjacency.of(store.links(), options.follow)
    found = tuple(
        _topic(index, group, nodes, schema, options.terms)
        for index, group in enumerate(components(adjacency))
        if len(group) >= options.min_size
    )
    return {"topics": found, "mixed_topics": sum(one.mixed for one in found)}


class RetrieveDualOptions(Frozen):
    """How far the topic branch reaches, and how much a node reached only that way is worth.

    `weight` below one is the whole claim of the branch: a node the question named is
    better evidence than a node discussed near something the question named, and the
    ranking should say so rather than letting a large topic flood the seeds.
    """

    limit: int = Field(LIMIT, gt=0)
    topics: int = Field(2, ge=0)
    weight: float = Field(0.5, ge=0.0, le=1.0)


@register("retrieve_dual", requires=("store", "index", "topics", "question"),
          produces=("hits",), options=RetrieveDualOptions)
def retrieve_dual(state: State, options: RetrieveDualOptions) -> State:
    """Rank nodes by what the question says and by the topics that share its words."""
    index: Index = state["index"]
    question: str = state["question"]
    direct = overlap(index, question)
    through = _through_topics(state["topics"], question, options)
    scores = {
        node_id: max(direct.get(node_id, 0.0), through.get(node_id, 0.0))
        for node_id in {*direct, *through}
    }
    ordered = sorted(scores.items(), key=lambda scored: (-scored[1], scored[0]))[:options.limit]
    nodes = state["store"].get_nodes([node_id for node_id, _ in ordered])
    return {"hits": tuple(
        Hit(node=node, score=scores[node.id],
            via="question" if node.id in direct else "topic")
        for node in nodes
    )}


def _through_topics(
    found: Iterable[Topic], question: str, options: RetrieveDualOptions
) -> dict[str, float]:
    """The members of the topics whose shared terms the question uses, at a reduced weight."""
    asked = set(tokenise(question))
    if not asked or not options.topics:
        return {}
    scored = [
        (len(asked & set(topic.terms)) / len(asked), topic)
        for topic in found
    ]
    best = sorted((pair for pair in scored if pair[0] > 0),
                  key=lambda pair: (-pair[0], pair[1].id))[:options.topics]
    return {
        member: score * options.weight
        for score, topic in best
        for member in topic.members
    }


def _topic(
    index: int, group: frozenset[str], nodes: dict[str, Node], schema: Schema | None, terms: int
) -> Topic:
    """One connected group as a topic: its members, their kinds, and the terms they share."""
    members = tuple(sorted(node_id for node_id in group if node_id in nodes))
    held = [nodes[node_id] for node_id in members]
    counted = Counter(term for node in held for term in set(tokenise(node.text())))
    shared = tuple(term for term, _count in counted.most_common(terms))
    labelled = [schema.label_of(node) for node in held] if schema is not None else []
    return Topic(
        id=f"t{index:03d}",
        label=" / ".join(labelled[:2]) or " ".join(shared[:2]) or f"topic {index}",
        terms=shared,
        members=members,
        kinds=tuple(sorted({node.type for node in held})),
    )
