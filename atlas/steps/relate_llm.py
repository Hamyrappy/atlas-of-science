"""Asking a model how the nodes of one segment stand to each other, one call per segment.

The mirror of `extract_llm`, and the same discipline: the predicates on offer are read
out of whatever pack was loaded, with the types each one connects, so this module names
no relation and swapping the pack swaps what may be claimed. The model is shown the
nodes that were already placed in this segment, under the reference each is cited by,
and is asked which pairs the text relates and which words say so. Offsets are never
asked for, and neither are node ids: it picks from references it was given, so an
endpoint it invents fails to resolve in `relate` and is dropped rather than guessed at.

Only nodes of the same segment are offered together. A relation across two segments is
a real thing and a model asked for one at this scale mostly produces plausible pairs
from separate paragraphs; a step that wants them should widen the window deliberately,
and say in its own module that it did.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field, ValidationError

from atlas.model import Frozen, Node, Schema
from atlas.steps import State, register
from atlas.steps.relate import Relation

if TYPE_CHECKING:
    from atlas.llm import ChatClient

RELATIONS = "relations"

PROMPT = """Read one {unit} of a source and say how the things already found in it are related.

Relations you may use, with the types each one connects:
{predicates}

Things found in this {unit}, by the reference you must use for them:
{nodes}

Rules:
- Use only the relations above, and only between the references listed above.
- Claim a relation only where this {unit} says so; do not infer one from background.
- Give every relation a quote copied character for character from the {unit}.
- Omit the relation if no exact quote in the {unit} supports it.
- Answer with {{"{key}": [...]}}; an empty list is a valid answer.

{unit} {number}:
{text}
"""


class RelateLlmOptions(Frozen):
    """The noun the prompt uses for a segment, as in `extract_llm` and for the same reason."""

    segment: str = Field(default="segment", min_length=1)


@register("relate_llm", requires=("sources", "nodes", "schema", "client"),
          produces=("relations", "malformed_relations", "tokens", "cached_replies"),
          options=RelateLlmOptions)
def relate_llm(state: State, options: RelateLlmOptions) -> State:
    """Ask once per segment that holds at least two nodes, and collect what comes back."""
    client: ChatClient = state["client"]
    schema: Schema = state["schema"]
    nodes: tuple[Node, ...] = state["nodes"]
    reply_schema = build_schema(schema)
    catalogue = _predicates(schema)
    relations: list[Relation] = []
    malformed = 0
    tokens = 0
    cached = 0
    for source in state["sources"]:
        for part in source.segments:
            here = [node for node in nodes if _in(node, source.id, part.number)]
            # One thing cannot be related to anything, and a call asking for it is spent.
            if len(here) < 2:
                continue
            prompt = PROMPT.format(
                unit=options.segment, predicates=catalogue, number=part.number,
                text=part.text, key=RELATIONS, nodes=_offered(here, schema),
            )
            body, reply = client.complete_json(prompt, reply_schema)
            parsed, unreadable = _relations(body, source.id, part.number)
            relations += parsed
            malformed += unreadable
            cached += int(reply.cached)
            tokens += 0 if reply.cached else reply.tokens
    return {"relations": tuple(relations), "malformed_relations": malformed,
            "tokens": tokens, "cached_replies": cached}


def build_schema(schema: Schema) -> dict:
    """The strict JSON schema for one reply: a list of quoted relations between references."""
    properties = {
        "predicate": {"type": "string", "enum": sorted(p.name for p in schema.predicates)},
        "src_ref": {"type": "string"},
        "dst_ref": {"type": "string"},
        "quote": {"type": "string"},
    }
    item = {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [RELATIONS],
        "properties": {RELATIONS: {"type": "array", "items": item}},
    }


def _in(node: Node, source_id: str, number: int) -> bool:
    """Whether a node was placed in this segment of this source."""
    return any(span.source_id == source_id and span.segment == number for span in node.spans)


def _offered(nodes: list[Node], schema: Schema) -> str:
    """The nodes a call may relate, each under the reference an answer would cite it by."""
    return "\n".join(f"- {node.ref} ({node.type}): {schema.label_of(node)}" for node in nodes)


def _predicates(schema: Schema) -> str:
    """One line per relation: its name, what it connects, what it means."""
    return "\n".join(
        f"- {p.name} ({p.domain} -> {p.range}): {p.description}" for p in schema.predicates
    )


def _relations(reply: dict, source_id: str, number: int) -> tuple[list[Relation], int]:
    """Read the relations out of one reply, counting the items that do not parse."""
    items = reply.get(RELATIONS)
    if not isinstance(items, list):
        return [], 0
    parsed: list[Relation] = []
    for item in items:
        try:
            parsed.append(Relation.model_validate({**item, "source_id": source_id,
                                                   "segment": number}))
        except (TypeError, ValidationError):
            continue
    return parsed, len(items) - len(parsed)
