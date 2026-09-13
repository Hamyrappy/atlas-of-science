"""Turning a document into typed cards, one model call per page.

The model returns typed statements each carrying a verbatim quote, which
`atlas.extract.relocate` places in the page text; a quote that cannot be placed
is dropped and counted rather than guessed at. Card ids are content hashes, so a
rerun over unchanged input writes the same cards. Edges are not extracted yet.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from atlas.contracts import Card, Document, Frozen, Ontology, TypeDef
from atlas.extract.relocate import locate
from atlas.ontology import validate_card

if TYPE_CHECKING:
    from atlas.llm import Client

STATEMENTS = "statements"

PROMPT = """Read one page of a document and extract typed statements from it.

Types you may use, with the fields each one takes:
{types}

Rules:
- Use only the types above, and fill only their fields. Skip whatever fits none of them.
- Give every statement a quote copied character for character from the page.
- Never paraphrase, shorten or repair a quote.
- Omit the statement if no exact quote on the page supports it.
- Set page to {page}.
- Answer with {{"{key}": [...]}}; an empty list is a valid answer.

Page {page}:
{text}
"""


class ExtractionResult(Frozen):
    """The cards one run produced, with a count of what it refused to write."""

    cards: tuple[Card, ...]
    dropped: int
    needs_review: int


class _Statement(BaseModel):
    """One item of the model's reply, before its quote has been located."""

    model_config = ConfigDict(extra="ignore")

    type: str
    fields: dict[str, str] = Field(default_factory=dict)
    quote: str


def build_schema(ontology: Ontology) -> dict:
    """The strict JSON schema for a page reply: a list of typed, quoted statements."""
    properties = {
        "type": {"type": "string", "enum": sorted(ontology.type_names())},
        "fields": {"type": "object", "additionalProperties": {"type": "string"}},
        "quote": {"type": "string"},
        "page": {"type": "integer"},
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


def extract_cards(
    document: Document, ontology: Ontology, client: Client, *,
    run_id: str, pages: Iterable[int] | None = None,
) -> ExtractionResult:
    """Extract cards from the given pages of a document, one model call per page."""
    numbers = [page.number for page in document.pages] if pages is None else pages
    schema = build_schema(ontology)
    catalogue = _catalogue(ontology)
    cards: list[Card] = []
    dropped = 0
    needs_review = 0
    for number in numbers:
        text = document.page_text(number)
        prompt = PROMPT.format(types=catalogue, page=number, text=text, key=STATEMENTS)
        statements, malformed = _statements(client.complete_json(prompt, schema))
        dropped += malformed
        for statement in statements:
            match = locate(document, statement.quote, number)
            if match is None:
                dropped += 1
                continue
            card = Card(
                id=_card_id(document.id, match.span.page, statement.type, statement.quote),
                type=statement.type,
                fields=statement.fields,
                spans=(match.span,),
                run_id=run_id,
                ontology_version=ontology.version,
            )
            if validate_card(card, ontology) != []:
                dropped += 1
                continue
            cards.append(card)
            needs_review += int(match.needs_review)
    return ExtractionResult(cards=tuple(cards), dropped=dropped, needs_review=needs_review)


def _statements(reply: dict) -> tuple[list[_Statement], int]:
    """Read the statements out of one reply, counting the items that do not parse."""
    items = reply.get(STATEMENTS)
    if not isinstance(items, list):
        return [], 0
    parsed: list[_Statement] = []
    for item in items:
        try:
            parsed.append(_Statement.model_validate(item))
        except ValidationError:
            continue
    return parsed, len(items) - len(parsed)


def _card_id(doc_id: str, page: int, type_name: str, quote: str) -> str:
    material = "\x00".join([doc_id, str(page), type_name, quote])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _catalogue(ontology: Ontology) -> str:
    """One line per type: its name, the fields it and its ancestors declare, its description."""
    lines = []
    for type_def in ontology.types:
        fields: list[str] = []
        walked: set[str] = set()
        current: TypeDef | None = type_def
        # Nothing checks the core file for a parent cycle, so the walk stops itself.
        while current is not None and current.name not in walked:
            walked.add(current.name)
            fields.extend(name for name in current.fields if name not in fields)
            current = ontology.find_type(current.parent) if current.parent else None
        lines.append(f"- {type_def.name} [{', '.join(fields)}]: {type_def.description}")
    return "\n".join(lines)
