"""Keeping the parts of a source that carry something, under the categories a run names.

A full-text extractor spends most of its calls on sentences that carry nothing and
then, on a long paper, runs out of budget somewhere in the middle. A salience pass
reads each segment once and says which regions of it are worth extracting from, under
which category, quoting each one. The regions become nodes like anything else, so the
decision is recorded rather than implicit, and a later pass can be pointed at them.

**The categories are a configuration and not a vocabulary.** Which distinctions matter
-- what is new here, what is defined here, what did not work, what the limits are --
belongs to the corpus and to the questions being asked of it, so they are named in the
manifest and this module never learns any of them. That also makes them measurable:
`kept` counts what was found per category, which is the number to watch, because the
failure mode of a salience pass is not noise. It is losing the negative result.

That failure is why nothing here filters. The pass adds what it found and takes nothing
away: a run that wants extraction confined to the kept passages says so by ordering its
steps, and a run that wants both keeps both. A step that silently dropped the rest of a
source would make its own recall unmeasurable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field, ValidationError

from atlas.model import Frozen
from atlas.steps import State, register
from atlas.steps.relocate import Statement

if TYPE_CHECKING:
    from atlas.llm import ChatClient

PASSAGES = "passages"

PROMPT = """Read one {unit} of a source and pick out the regions worth keeping.

Categories to look for:
{categories}

Rules:
- Quote each region character for character from the {unit}; never paraphrase or repair.
- Use only the categories above, exactly as written.
- Keep a region once per category it carries; a region may carry more than one.
- Keep nothing you cannot quote exactly, and nothing that carries none of the categories.
- Summarise each region in one short phrase, in the language of the {unit}.
- Answer with {{"{key}": [...]}}; an empty list is a valid answer.

{unit} {number}:
{text}
"""


class SalienceOptions(Frozen):
    """What to look for, and what a kept region becomes.

    `categories` has no default because a default would be a vocabulary, and this
    package holds none. `type` and `field` name a type of the loaded pack and one of
    its fields, so a kept region is an ordinary node of an ordinary type: it is
    validated, bound to a span and asserted like everything else, and a pack that does
    not declare the type refuses the whole pass at `validate` rather than here.
    """

    categories: tuple[str, ...] = Field(min_length=1)
    type: str = Field(min_length=1)
    field: str = Field(default="category", min_length=1)
    summary_field: str = Field(default="summary", min_length=1)
    segment: str = Field(default="segment", min_length=1)


@register("salience_llm", requires=("sources", "client"),
          produces=("statements", "kept", "tokens", "cached_replies"),
          options=SalienceOptions)
def salience_llm(state: State, options: SalienceOptions) -> State:
    """Read every segment once and keep the regions that carry one of the named categories.

    Adds to whatever statements the state already holds, so this can run before an
    extractor or after one without either of them knowing about it.
    """
    client: ChatClient = state["client"]
    reply_schema = build_schema(options.categories)
    listed = "\n".join(f"- {category}" for category in options.categories)
    statements: list[Statement] = list(state.get("statements", ()))
    kept = dict.fromkeys(options.categories, 0)
    tokens = 0
    cached = 0
    for source in state["sources"]:
        for part in source.segments:
            prompt = PROMPT.format(unit=options.segment, categories=listed, number=part.number,
                                   text=part.text, key=PASSAGES)
            body, reply = client.complete_json(prompt, reply_schema)
            for passage in _passages(body, options.categories):
                kept[passage["category"]] += 1
                statements.append(Statement(
                    source_id=source.id,
                    segment=part.number,
                    type=options.type,
                    fields={options.field: passage["category"],
                            options.summary_field: passage["summary"]},
                    quote=passage["quote"],
                ))
            cached += int(reply.cached)
            tokens += 0 if reply.cached else reply.tokens
    return {"statements": tuple(statements), "kept": kept,
            "tokens": tokens, "cached_replies": cached}


def build_schema(categories: tuple[str, ...]) -> dict:
    """The strict JSON schema for one reply: quoted regions under one of the named categories."""
    properties = {
        "category": {"type": "string", "enum": list(categories)},
        "quote": {"type": "string"},
        "summary": {"type": "string"},
    }
    item = {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [PASSAGES],
        "properties": {PASSAGES: {"type": "array", "items": item}},
    }


def _passages(reply: dict, categories: tuple[str, ...]) -> list[dict]:
    """The readable passages of one reply, under a category that was actually offered."""
    items = reply.get(PASSAGES)
    if not isinstance(items, list):
        return []
    found = []
    for item in items:
        try:
            passage = _Passage.model_validate(item)
        except (TypeError, ValidationError):
            continue
        if passage.category in categories and passage.quote.strip():
            found.append(passage.model_dump())
    return found


class _Passage(Frozen):
    """One kept region as the model returns it, before it has been placed in the text."""

    category: str
    quote: str
    summary: str = ""
