"""Tests for the definition a pooled candidate has to carry before it can be judged.

The form is the point: genus and differentia, two named parts, so the reuse question is
answerable in one reading. A reply that says the term is the closest existing one is
treated as a reuse -- the candidate is pushed to certainty and the gate in `promote`
refuses it by name -- and a reply missing either part leaves the candidate as it was
rather than half-defining it.
"""

from __future__ import annotations

from atlas.llm import Reply
from atlas.model import Schema, TypeDef
from atlas.steps.define_llm import DefineLlmOptions, define_llm
from atlas.steps.induce import Candidate, PromoteOptions, promote

SCHEMA = Schema(version="0" * 12, types=(TypeDef(name="Study", description="An investigation."),))
DEFAULTS = DefineLlmOptions()
PLAIN = Candidate(term="c", label="Calibration", variants=("Calibration",),
                  examples=("a calibration step",), nearest="Study", similarity=0.2,
                  families=("a", "b", "c"), rounds=2)


class StubClient:
    def __init__(self, *bodies: dict) -> None:
        self.bodies = list(bodies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None,
                 system: str | None = None) -> Reply:
        raise AssertionError("defining asks for JSON, not prose")

    def complete_json(self, prompt: str, schema: dict, *,
                      system: str | None = None) -> tuple[dict, Reply]:
        self.prompts.append(prompt)
        body = self.bodies.pop(0) if self.bodies else {}
        return body, Reply(text="", usage={}, cached=False)


def definition(genus: str, differentia: str, same: bool = False) -> dict:
    return {"definition": {"genus": genus, "differentia": differentia,
                           "same_as_nearest": same}}


def test_a_definition_is_the_genus_and_the_differentia_joined() -> None:
    client = StubClient(definition("a preparation step", "performed before measurement"))

    result = define_llm({"candidates": (PLAIN,), "client": client}, DEFAULTS)

    assert result["candidates"][0].definition == (
        "a preparation step, performed before measurement"
    )
    assert result["defined"] == 1


def test_a_reply_calling_it_the_nearest_term_makes_it_a_reuse_the_gate_refuses() -> None:
    client = StubClient(definition("an investigation", "", same=True))

    defined = define_llm({"candidates": (PLAIN,), "client": client}, DEFAULTS)["candidates"]
    judged = promote({"candidates": defined, "schema": SCHEMA}, PromoteOptions())

    assert defined[0].similarity == 1.0
    assert judged["promoted"] == ()
    assert "reuse 'Study' instead" in judged["refused"][0].reason


def test_half_a_definition_leaves_the_candidate_undefined() -> None:
    client = StubClient(definition("a preparation step", "   "))

    [candidate] = define_llm({"candidates": (PLAIN,), "client": client}, DEFAULTS)["candidates"]

    assert candidate.definition == ""


def test_an_unreadable_reply_leaves_the_candidate_as_it_was() -> None:
    client = StubClient({"definition": "a sentence, not an object"})

    [candidate] = define_llm({"candidates": (PLAIN,), "client": client}, DEFAULTS)["candidates"]

    assert candidate == PLAIN


def test_a_candidate_that_already_carries_one_is_not_asked_about_again() -> None:
    held = PLAIN.model_copy(update={"definition": "a step, reviewed by a person"})
    client = StubClient()

    result = define_llm({"candidates": (held,), "client": client}, DEFAULTS)

    assert client.prompts == []
    assert result["defined"] == 0
    assert result["candidates"][0].definition == "a step, reviewed by a person"


def test_redefining_is_something_a_run_has_to_ask_for() -> None:
    held = PLAIN.model_copy(update={"definition": "a step, reviewed by a person"})
    client = StubClient(definition("a preparation step", "performed before measurement"))

    result = define_llm({"candidates": (held,), "client": client},
                        DefineLlmOptions(redefine=True))

    assert result["defined"] == 1


def test_the_prompt_shows_the_quotes_and_the_closest_existing_term() -> None:
    client = StubClient()

    define_llm({"candidates": (PLAIN,), "client": client}, DEFAULTS)

    [prompt] = client.prompts
    assert "a calibration step" in prompt
    assert "Study" in prompt
