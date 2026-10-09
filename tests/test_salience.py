"""Tests for the pass that keeps the parts of a source worth extracting from.

Two claims are under test. The categories are a configuration and never a vocabulary:
the step offers exactly what it was given and refuses a reply naming anything else. And
the pass adds without removing, so its own recall stays measurable -- `kept` is the
number to watch, because the way a salience pass fails is by losing the negative result
rather than by keeping noise.
"""

from __future__ import annotations

from atlas.llm import Reply
from atlas.model import Segment, Source
from atlas.steps.relocate import Statement
from atlas.steps.salience import SalienceOptions, build_schema, salience_llm

TEXT = (
    "We introduce a calibration step that raises the yield.\n"
    "The effect was not observed at low pressure, which limits the claim.\n"
)
SOURCE = Source(id="paper", origin="paper.txt", segments=(Segment(number=1, text=TEXT),))
OPTIONS = SalienceOptions(categories=("contribution", "limitation"), type="Passage")


class StubClient:
    """A client returning one canned JSON body per call, with the prompts it was given."""

    def __init__(self, *bodies: dict) -> None:
        self.bodies = list(bodies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None,
                 system: str | None = None) -> Reply:
        raise AssertionError("the salience pass asks for JSON, not prose")

    def complete_json(self, prompt: str, schema: dict, *,
                      system: str | None = None) -> tuple[dict, Reply]:
        self.prompts.append(prompt)
        body = self.bodies.pop(0) if self.bodies else {"passages": []}
        return body, Reply(text="", usage={"total_tokens": 7}, cached=False)


def passages(*items: tuple[str, str, str]) -> dict:
    return {"passages": [{"category": c, "quote": q, "summary": s} for c, q, s in items]}


def test_a_kept_region_becomes_a_statement_of_the_configured_type() -> None:
    client = StubClient(passages(("contribution", "a calibration step", "new step")))

    result = salience_llm({"sources": (SOURCE,), "client": client}, OPTIONS)

    [statement] = result["statements"]
    assert isinstance(statement, Statement)
    assert statement.type == "Passage"
    assert statement.fields == {"category": "contribution", "summary": "new step"}
    assert statement.quote == "a calibration step"


def test_what_was_kept_is_counted_per_category_so_recall_is_measurable() -> None:
    client = StubClient(passages(
        ("contribution", "a calibration step", "new step"),
        ("limitation", "not observed at low pressure", "bounded claim"),
    ))

    result = salience_llm({"sources": (SOURCE,), "client": client}, OPTIONS)

    assert result["kept"] == {"contribution": 1, "limitation": 1}


def test_a_category_nothing_was_found_for_is_reported_as_zero_not_omitted() -> None:
    client = StubClient(passages(("contribution", "a calibration step", "new step")))

    result = salience_llm({"sources": (SOURCE,), "client": client}, OPTIONS)

    assert result["kept"]["limitation"] == 0


def test_a_category_that_was_not_offered_is_dropped() -> None:
    client = StubClient(passages(("novelty", "a calibration step", "invented")))

    result = salience_llm({"sources": (SOURCE,), "client": client}, OPTIONS)

    assert result["statements"] == ()
    assert result["kept"] == {"contribution": 0, "limitation": 0}


def test_the_pass_adds_to_what_the_state_already_holds() -> None:
    before = Statement(source_id="paper", segment=1, type="Thing", quote="We introduce")
    client = StubClient(passages(("contribution", "a calibration step", "new step")))

    result = salience_llm(
        {"sources": (SOURCE,), "client": client, "statements": (before,)}, OPTIONS
    )

    assert result["statements"][0] is before
    assert len(result["statements"]) == 2


def test_an_unquotable_region_is_not_kept() -> None:
    client = StubClient(passages(("contribution", "   ", "nothing")))

    assert salience_llm({"sources": (SOURCE,), "client": client}, OPTIONS)["statements"] == ()


def test_the_prompt_offers_the_configured_categories_and_the_schema_enforces_them() -> None:
    client = StubClient()

    salience_llm({"sources": (SOURCE,), "client": client}, OPTIONS)

    [prompt] = client.prompts
    assert "- contribution" in prompt and "- limitation" in prompt
    enum = build_schema(OPTIONS.categories)["properties"]["passages"]["items"]
    assert enum["properties"]["category"]["enum"] == ["contribution", "limitation"]


def test_a_cached_reply_costs_nothing_this_run() -> None:
    class Cached(StubClient):
        def complete_json(self, prompt: str, schema: dict, *,
                          system: str | None = None) -> tuple[dict, Reply]:
            return {"passages": []}, Reply(text="", usage={"total_tokens": 9}, cached=True)

    result = salience_llm({"sources": (SOURCE,), "client": Cached()}, OPTIONS)

    assert result["tokens"] == 0
    assert result["cached_replies"] == 1
