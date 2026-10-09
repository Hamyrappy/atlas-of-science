"""Asking a model for a definition of a pooled candidate, in the one form that can be checked.

A candidate with no definition cannot be judged: "it appeared in four papers" says the
corpus keeps using a word and says nothing about what the word means, and the gate in
`promote` refuses it for exactly that reason. This step is what fills the gap.

The definition is asked for in **genus and differentia** form -- what kind of thing it
is, and what distinguishes it from the nearest thing of that kind. That is not a style
preference. A definition in that form can be checked by a person in one reading, and it
makes the reuse question answerable: if the differentia is empty, or says only that the
term is common, the candidate *is* the nearest existing term and should be reused rather
than minted. A free-text paragraph hides that; two named parts cannot.

The model is shown the candidate's surface forms, the quotes it was found in, and the
closest term the loaded schema already has -- so that "this is just that" is one of the
answers it can give, and the one it is asked to prefer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field, ValidationError

from atlas.model import Frozen
from atlas.steps import State, register
from atlas.steps.induce import Candidate

if TYPE_CHECKING:
    from atlas.llm import ChatClient

DEFINITION = "definition"

PROMPT = """Define one term the way a dictionary of a field defines one.

Term, as it appears in the sources: {label}
Other spellings seen: {variants}
Quotes it was found in:
{examples}

The closest term the current vocabulary already has: {nearest}

Rules:
- Give the genus: the kind of thing this is, in a few words.
- Give the differentia: what distinguishes it from other things of that kind.
- If the term means the same as the closest existing term, say so by setting
  "same_as_nearest" to true and leave the differentia empty.
- Use only what the quotes support; do not add background knowledge about the field.
- Answer with {{"{key}": {{...}}}}.
"""


class DefineLlmOptions(Frozen):
    """Whether a candidate that already carries a definition is asked about again.

    It is not, by default: a definition survives in the registry across rounds, and
    re-asking would spend a call per candidate per run to get a differently worded
    version of a decision somebody may already have reviewed.
    """

    redefine: bool = False


@register("define_llm", requires=("candidates", "client"), produces=("candidates", "defined"),
          options=DefineLlmOptions)
def define_llm(state: State, options: DefineLlmOptions) -> State:
    """Give every undefined candidate a genus-and-differentia definition, or mark it a reuse."""
    client: ChatClient = state["client"]
    reply_schema = build_schema()
    defined: list[Candidate] = []
    asked = 0
    for candidate in state["candidates"]:
        if candidate.definition and not options.redefine:
            defined.append(candidate)
            continue
        asked += 1
        body, _reply = client.complete_json(_prompt(candidate), reply_schema)
        defined.append(_defined(candidate, body))
    return {"candidates": tuple(defined), "defined": asked}


def build_schema() -> dict:
    """The strict JSON schema for one reply: two named parts and a reuse flag."""
    properties = {
        "genus": {"type": "string"},
        "differentia": {"type": "string"},
        "same_as_nearest": {"type": "boolean"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [DEFINITION],
        "properties": {
            DEFINITION: {"type": "object", "additionalProperties": False,
                         "required": list(properties), "properties": properties}
        },
    }


def _prompt(candidate: Candidate) -> str:
    return PROMPT.format(
        label=candidate.label,
        variants=", ".join(candidate.variants) or "none",
        examples="\n".join(f"  > {quote}" for quote in candidate.examples) or "  (none)",
        nearest=candidate.nearest or "none",
        key=DEFINITION,
    )


def _defined(candidate: Candidate, body: dict) -> Candidate:
    """The candidate with what the model said, or unchanged if the reply cannot be read.

    A reply claiming the term is the closest existing one raises its similarity to
    certainty rather than writing a definition: the gate in `promote` then refuses it
    as a reuse, which is the outcome the answer asked for and is recorded as such.
    """
    try:
        parsed = _Definition.model_validate(body.get(DEFINITION) or {})
    except (TypeError, ValidationError):
        return candidate
    if parsed.same_as_nearest and candidate.nearest:
        return candidate.model_copy(update={"similarity": 1.0})
    if not parsed.genus.strip() or not parsed.differentia.strip():
        return candidate
    return candidate.model_copy(
        update={"definition": f"{parsed.genus.strip()}, {parsed.differentia.strip()}"}
    )


class _Definition(Frozen):
    """One definition as the model returns it, before it has been judged."""

    genus: str = ""
    differentia: str = ""
    same_as_nearest: bool = Field(default=False)
