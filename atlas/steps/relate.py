"""Turning a claimed relation into a link, under the same rule that governs a node.

Until this step existed the library could mark a corpus up into typed things and could
not say how any two of them stood to each other, which is the half of markup an
architecture that walks a graph is built on. It is deliberately the mirror of
`relocate`: an extractor claims that two things it has already found are related and
quotes the text saying so, and the claim becomes a `Link` only if the quote can be
placed and the pack allows that predicate between those two types.

Nothing is invented for a relation that a node would not be allowed to invent. A quote
that cannot be located is dropped and counted. A predicate the pack does not declare is
dropped and counted. A predicate declared between other types than the ones at hand is
dropped and counted, with the violation kept, because "the model related a document to
a reagent" is the kind of error a run has to be able to show rather than total.

Endpoints are named by `Node.ref`, which is what an extractor was shown and what an
answer cites. Content hashes are not put in front of a model and are not asked back
from it: a reference is short, stable across runs and already the library's public name
for a node.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from atlas.model import Link, Node, Schema, Source
from atlas.steps import Nothing, State, register
from atlas.steps.relocate import locate


class Relation(BaseModel):
    """What an extractor claims about two nodes, before the claim has been placed.

    The contract between any relation extractor and this step, declared here for the
    same reason `Statement` is declared in `relocate`: the step that checks a claim owns
    the shape of the claim. Undeclared keys are ignored rather than fatal, because a
    model volunteers them.
    """

    model_config = ConfigDict(frozen=True)

    source_id: str
    segment: int
    predicate: str
    src_ref: str = Field(description="`Node.ref` of the node the relation runs from")
    dst_ref: str = Field(description="`Node.ref` of the node it runs to")
    quote: str


@register("relate", requires=("sources", "nodes", "relations", "schema"),
          produces=("links", "unrelated", "relation_violations"), options=Nothing)
def relate(state: State) -> State:
    """Place every claimed relation and mint a link for each one the pack accepts."""
    sources: dict[str, Source] = {source.id: source for source in state["sources"]}
    nodes: dict[str, Node] = {node.ref: node for node in state["nodes"]}
    schema: Schema = state["schema"]
    links: dict[str, Link] = {}
    unrelated = 0
    violations: list[str] = []
    for relation in state["relations"]:
        source = sources.get(relation.source_id)
        src, dst = nodes.get(relation.src_ref), nodes.get(relation.dst_ref)
        if source is None or src is None or dst is None:
            unrelated += 1
            continue
        match = locate(source, relation.quote, relation.segment)
        if match is None:
            unrelated += 1
            continue
        link = Link.of(
            predicate=relation.predicate,
            src=src.id,
            dst=dst.id,
            spans=(match.span,),
            schema_version=schema.version,
        )
        # The pack rules on the relation, exactly as `validate` rules on a node: a
        # predicate it does not declare, or declares between other types, is a defect
        # of this pass and is reported with the case rather than counted away.
        problems = schema.validate_link(link, src.type, dst.type)
        if problems:
            violations += problems
            continue
        links.setdefault(link.id, link)
    return {"links": tuple(links.values()), "unrelated": unrelated,
            "relation_violations": tuple(violations)}
