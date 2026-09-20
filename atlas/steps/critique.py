"""Checking what an extractor produced against the text it came from, before anything is asserted.

A single extraction pass gets things wrong in ways that are cheap to detect and
expensive to discover later: it fills a field with a phrase that is nowhere in the
quote, leaves the field that names the thing empty, or records as a finding a sentence
that says the effect was not found. None of those need a model to catch. They need
somebody to look, which is what this step is.

Every check here is **deterministic and local**: it compares one node against its own
span and its own type, and produces a `Finding` naming the check, the node and the
place. Nothing is repaired -- repair is a separate step with a budget -- and nothing is
dropped, because a run that silently discarded its own mistakes could not report how
many it made. `findings` travels on, and a configuration decides what to do about it.

The negation check is the one worth explaining. A node whose span carries a negation
marker while its own fields read as a plain finding is not necessarily wrong -- "no
increase was observed" is a perfectly good negative result, correctly extracted. What
it is, always, is worth a second look, because it is where an extractor most often
turns a refutation into a confirmation by dropping one word. So the check reports rather
than judges, the markers come from the configuration (they are words of a language, not
of this library), and the finding says which marker it saw.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Node, Schema
from atlas.steps import State, register
from atlas.text import fold, normalise

Check = Literal["ungrounded", "unnamed", "negation", "thin", "untyped"]
"""What a deterministic critic can say about a node by looking at it and its own span."""


class Finding(Frozen):
    """One thing wrong, or worth a second look, about one node."""

    node_id: str
    check: Check
    detail: str
    field: str = ""

    @property
    def repairable(self) -> bool:
        """Whether a re-extraction could plausibly fix it, as opposed to a judgement call.

        A negation is not repairable by asking again: the extractor already read the
        sentence and this is a question about what it means, which is a person's or a
        reviewer's to settle.
        """
        return self.check in ("ungrounded", "unnamed", "thin")


class CritiqueOptions(Frozen):
    """What the critics are allowed to assume, and the words the negation check looks for.

    `negations` is empty by default because negation markers are words of a language and
    this package holds none. A run that wants the check names them, in the language of
    its corpus, and gets a finding per marker it saw.
    """

    negations: tuple[str, ...] = ()
    min_quote: int = Field(12, ge=0)
    grounded_fields: tuple[str, ...] = Field(
        default=(), description="Fields whose value must appear in the span; empty means none"
    )


@register("critique", requires=("nodes", "schema"), produces=("findings",),
          options=CritiqueOptions)
def critique(state: State, options: CritiqueOptions) -> State:
    """Run every deterministic critic over every node and collect what they said."""
    schema: Schema = state["schema"]
    found: list[Finding] = []
    for node in state["nodes"]:
        found += check(node, schema, options)
    return {"findings": tuple(found)}


def check(node: Node, schema: Schema, options: CritiqueOptions) -> list[Finding]:
    """Everything the critics say about one node; an empty list means they had nothing."""
    found: list[Finding] = []
    quote = " ".join(span.text for span in node.spans)
    folded, _offsets = fold(quote)
    folded = folded.casefold()

    if schema.find_type(node.type) is None:
        found.append(Finding(node_id=node.id, check="untyped",
                             detail=f"type {node.type!r} is not one the pack declares"))
    elif not normalise(schema.label_of(node)) or schema.label_of(node) == node.type:
        found.append(Finding(
            node_id=node.id, check="unnamed",
            detail="nothing fills the field that names it, so it reads as its type",
        ))

    if len(normalise(quote)) < options.min_quote:
        found.append(Finding(node_id=node.id, check="thin",
                             detail=f"the whole evidence is {len(normalise(quote))} characters"))

    found += [
        Finding(node_id=node.id, check="ungrounded", field=field,
                detail=f"{node.fields[field]!r} does not appear in the quote it was taken from")
        for field in options.grounded_fields
        if node.fields.get(field) and not _grounded(node.fields[field], folded)
    ]
    found += [
        Finding(node_id=node.id, check="negation",
                detail=f"the quote carries {marker!r}; check the claim was not inverted")
        for marker in options.negations
        if marker.casefold() in folded
    ]
    return found


def repairable(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    """The findings a re-extraction could plausibly fix, which is what `repair_llm` is given."""
    return tuple(finding for finding in findings if finding.repairable)


def _grounded(value: str, folded_quote: str) -> bool:
    """Whether a field value can be found in the quote, once both have been folded."""
    folded_value, _offsets = fold(value)
    return folded_value.casefold() in folded_quote
