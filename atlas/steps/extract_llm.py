"""Turning a source into typed statements, one model call per segment.

The types on offer are read out of whatever schema was loaded, so this module knows
only that types have names, fields and a description, and nothing about what any of
them mean; swapping the pack swaps the vocabulary without touching a line here. The
model is asked for a verbatim quote and never for offsets, which `relocate` recovers.

The noun a prompt uses for a segment is an option: a reader of PDFs calls them pages
and a reader of transcripts calls them turns, while the metamodel calls neither.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from atlas.model import Schema
from atlas.steps import State, register
from atlas.steps.relocate import Statement

if TYPE_CHECKING:
    from atlas.llm import Client

STATEMENTS = "statements"

PROMPT = """Read one {unit} of a source and extract typed statements from it.

Types you may use, with the fields each one takes:
{types}

Rules:
- Use only the types above, and fill only their fields. Skip whatever fits none of them.
- Give every statement a quote copied character for character from the {unit}.
- Never paraphrase, shorten or repair a quote.
- Omit the statement if no exact quote in the {unit} supports it.
- Answer with {{"{key}": [...]}}; an empty list is a valid answer.

{unit} {number}:
{text}
"""


@register("extract_llm")
def extract_llm(state: State, *, segment: str = "segment") -> State:
    """Call the model once per segment of every source, for statements nothing has placed yet."""
    client: Client = state["client"]
    schema: Schema = state["schema"]
    reply_schema = build_schema(schema)
    catalogue = _catalogue(schema)
    statements: list[Statement] = []
    malformed = 0
    for source in state["sources"]:
        for part in source.segments:
            prompt = PROMPT.format(
                unit=segment, types=catalogue, number=part.number, text=part.text, key=STATEMENTS
            )
            reply = client.complete_json(prompt, reply_schema)
            parsed, unreadable = _statements(reply, source.id, part.number)
            statements += parsed
            malformed += unreadable
    return {"statements": tuple(statements), "malformed": malformed}


def build_schema(schema: Schema) -> dict:
    """The strict JSON schema for one reply: a list of typed, quoted statements."""
    properties = {
        "type": {"type": "string", "enum": sorted(schema.type_names())},
        "fields": {"type": "object", "additionalProperties": {"type": "string"}},
        "quote": {"type": "string"},
    }
    # Strict schemas require every property, so the model cannot omit the quote.
    item = {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}
    # The client parses one JSON object, so the list of statements travels under a key.
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [STATEMENTS],
        "properties": {STATEMENTS: {"type": "array", "items": item}},
    }


def _statements(reply: dict, source_id: str, number: int) -> tuple[list[Statement], int]:
    """Read the statements out of one reply, counting the items that do not parse.

    Where the statement came from is known here and is not asked of the model: it
    would state the segment it was shown, which is what the caller already passed.
    """
    items = reply.get(STATEMENTS)
    if not isinstance(items, list):
        return [], 0
    parsed: list[Statement] = []
    for item in items:
        try:
            parsed.append(Statement.model_validate({**item, "source_id": source_id,
                                                    "segment": number}))
        except (TypeError, ValidationError):
            continue
    return parsed, len(items) - len(parsed)


def _catalogue(schema: Schema) -> str:
    """One line per type: its name, the fields it and its ancestors declare, its description."""
    return "\n".join(
        f"- {type_def.name} "
        f"[{', '.join(field.name for field in schema.declared_fields(type_def.name))}]: "
        f"{type_def.description}"
        for type_def in schema.types
    )
