"""Giving an extractor its mistakes back, twice at most, and quarantining what survives.

A critic that only reports is an audit. This is the loop that acts on it: nodes with a
repairable finding are put back in front of the model, with the finding, the source
segment and nothing else to guess at, and what comes back is placed and checked exactly
as the first attempt was. A node that is still wrong after the budget is **quarantined**
-- held out of what the run asserts, with the findings that condemned it -- rather than
either asserted or thrown away.

The budget is the point of the module. An unbounded repair loop on a model that is
confidently wrong is a way to spend a corpus's worth of tokens converging on the same
mistake, so `rounds` is two by default and the quarantine is where exhaustion lands. An
exhausted budget never turns into an acceptance: `quarantined` is a list, `repaired` is
a count, and the difference between them is what a run reports.

What comes out is a fresh set of statements for `relocate` to place, not a patched node.
A node is a content hash over its type, its fields and the span it was cut from; a
"repaired" node is a different node, and pretending otherwise would put two different
claims under one id.

Every node comes out as a statement, including the ones nothing was said against. That
is not waste: placing a quote is deterministic, so a node that was fine is placed at the
same offsets, hashes to the same id and comes back unchanged -- and the alternative,
returning two collections for a later step to union, is a seam where half a run's nodes
get dropped by whoever forgets. One key out, one `relocate` after it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field, ValidationError

from atlas.model import Frozen, Node, Schema
from atlas.steps import State, register
from atlas.steps.critique import Finding, repairable
from atlas.steps.relocate import Statement

if TYPE_CHECKING:
    from atlas.llm import ChatClient

STATEMENT = "statement"

PROMPT = """One extracted statement was checked and found wrong. Correct it or withdraw it.

What was extracted:
  type: {type}
  fields: {fields}
  quote: {quote}

What the check said:
{findings}

The {unit} it came from:
{text}

Rules:
- Keep the same type unless the check says the type is wrong.
- Give a quote copied character for character from the {unit} above.
- Fill the fields from what the quote actually says; do not carry over a value the
  check objected to.
- If the {unit} does not support any correct version of this statement, set "withdraw"
  to true and leave the rest as it is.
- Answer with {{"{key}": {{...}}}}.
"""


class Quarantined(Frozen):
    """One node held out of what a run asserts, with everything said against it."""

    node: Node
    findings: tuple[Finding, ...]
    rounds: int = Field(description="How many repair attempts it survived")


class RepairOptions(Frozen):
    """How many attempts a wrong statement gets before it is held out of the run."""

    rounds: int = Field(2, ge=0, le=5)
    segment: str = Field(default="segment", min_length=1)


@register("repair_llm", requires=("nodes", "findings", "sources", "schema", "client"),
          produces=("statements", "quarantined", "repaired"), options=RepairOptions)
def repair_llm(state: State, options: RepairOptions) -> State:
    """Ask again about every repairable node, and quarantine what is still wrong after the budget.

    Returns statements: the untouched nodes turned back into the claims they were made
    from, plus the corrected ones. `relocate` places all of them, and the untouched ones
    hash to exactly the ids they already had.
    """
    client: ChatClient = state["client"]
    schema: Schema = state["schema"]
    segments = {
        (source.id, part.number): part.text
        for source in state["sources"] for part in source.segments
    }
    against: dict[str, list[Finding]] = {}
    for finding in state["findings"]:
        against.setdefault(finding.node_id, []).append(finding)
    reply_schema = build_schema(schema)

    statements: list[Statement] = []
    quarantined: list[Quarantined] = []
    repaired = 0
    for node in state["nodes"]:
        findings = tuple(against.get(node.id, ()))
        if not repairable(findings):
            statements.append(_as_statement(node))
            continue
        span = node.spans[0]
        text = segments.get((span.source_id, span.segment), "")
        corrected = _attempt(client, node, findings, text, reply_schema, options)
        if corrected is None:
            quarantined.append(Quarantined(node=node, findings=findings, rounds=options.rounds))
            continue
        repaired += 1
        statements.append(corrected)
    return {"statements": tuple(statements), "quarantined": tuple(quarantined),
            "repaired": repaired}


def _as_statement(node: Node) -> Statement:
    """A node turned back into the claim it was made from, so one `relocate` places them all."""
    span = node.spans[0]
    return Statement(source_id=span.source_id, segment=span.segment, type=node.type,
                     fields=node.fields, quote=span.text)


def build_schema(schema: Schema) -> dict:
    """The strict JSON schema for one repair: a corrected statement, or a withdrawal."""
    properties = {
        "type": {"type": "string", "enum": sorted(schema.type_names())},
        "fields": {"type": "object", "additionalProperties": {"type": "string"}},
        "quote": {"type": "string"},
        "withdraw": {"type": "boolean"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [STATEMENT],
        "properties": {
            STATEMENT: {"type": "object", "additionalProperties": False,
                        "required": list(properties), "properties": properties}
        },
    }


def _attempt(
    client: ChatClient,
    node: Node,
    findings: tuple[Finding, ...],
    text: str,
    reply_schema: dict,
    options: RepairOptions,
) -> Statement | None:
    """Ask up to `rounds` times, and return the first answer that is a usable statement."""
    span = node.spans[0]
    for _round in range(options.rounds):
        prompt = PROMPT.format(
            type=node.type, fields=node.fields, quote=span.text, unit=options.segment,
            findings="\n".join(f"- {one.check}: {one.detail}" for one in findings),
            text=text, key=STATEMENT,
        )
        body, _reply = client.complete_json(prompt, reply_schema)
        corrected = body.get(STATEMENT)
        # A withdrawal is an answer and ends the loop; a reply that cannot be read is
        # not an answer, and spends one of the attempts rather than all of them.
        if isinstance(corrected, dict) and corrected.get("withdraw"):
            return None
        if not isinstance(corrected, dict):
            continue
        try:
            return Statement.model_validate({
                "source_id": span.source_id, "segment": span.segment,
                "type": corrected.get("type", node.type),
                "fields": corrected.get("fields") or {},
                "quote": corrected.get("quote", ""),
            })
        except (TypeError, ValidationError):
            continue
    return None
