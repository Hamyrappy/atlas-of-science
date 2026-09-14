"""Tests for the extraction step, driven by a stub client that returns canned replies.

The schema here is invented for the test: the step reads the types on offer out of
whichever schema it is given, so nothing it does may depend on what they are called.
"""

from __future__ import annotations

from atlas.llm import Reply
from atlas.model import FieldDef, Schema, Segment, Source, TypeDef
from atlas.steps.extract_llm import PROMPT, STATEMENTS, build_schema, extract_llm

FIRST = "1 Introduction\nA clean signal is hard to recover from noise.\n"
SECOND = "2 Results\nThe error falls to 0.12, against 0.19 for the baseline.\n"

SOURCE = Source(
    id="src-1",
    origin="fixtures/src-1.pdf",
    segments=(Segment(number=1, text=FIRST), Segment(number=2, text=SECOND)),
)

SCHEMA = Schema(
    version="a1b2c3d4e5f6",
    types=(
        TypeDef(
            name="Thing",
            fields=(FieldDef(name="name"),),
            description="Anything the text names.",
        ),
        TypeDef(
            name="Measure",
            parent="Thing",
            fields=(FieldDef(name="value"),),
            description="A quantity the text reports.",
        ),
    ),
)


class FakeClient:
    """A client stub with the signature of `complete_json`, replaying canned replies.

    Every reply is charged for 10 tokens; the ones beyond `paid` come back marked cached,
    which is how the step is asked to tell what a pass spent from what it spent earlier.
    """

    def __init__(self, *replies: list[dict], paid: int = 99) -> None:
        self.replies = [{STATEMENTS: reply} for reply in replies]
        self.prompts: list[str] = []
        self.paid = paid

    def complete_json(self, prompt: str, schema: dict, *,
                      system: str | None = None) -> tuple[dict, Reply]:
        self.prompts.append(prompt)
        body = self.replies.pop(0) if self.replies else {STATEMENTS: []}
        cached = len(self.prompts) > self.paid
        return body, Reply(text="", usage={"total_tokens": 10}, cached=cached)


def run(*replies: list[dict], paid: int = 99, **options: str) -> dict:
    client = FakeClient(*replies, paid=paid)
    state = extract_llm({"sources": (SOURCE,), "schema": SCHEMA, "client": client}, **options)
    return state | {"client": client}


def test_a_reply_becomes_statements_bound_to_the_segment_they_were_read_from() -> None:
    state = run(
        [{"type": "Thing", "fields": {"name": "a clean signal"}, "quote": "A clean signal"}],
        [{"type": "Measure", "fields": {"value": "0.12"}, "quote": "The error falls to 0.12"}],
    )

    assert state["malformed"] == 0
    assert [(s.type, s.segment) for s in state["statements"]] == [("Thing", 1), ("Measure", 2)]
    assert state["statements"][0].source_id == SOURCE.id
    assert state["statements"][1].quote == "The error falls to 0.12"


def test_one_call_per_segment_with_that_segment_in_the_prompt() -> None:
    state = run()

    prompts = state["client"].prompts
    assert len(prompts) == 2
    assert FIRST in prompts[0]
    assert SECOND in prompts[1]


def test_the_prompt_offers_the_types_of_the_loaded_schema_with_inherited_fields() -> None:
    prompt = run()["client"].prompts[0]

    assert "- Thing [name]: Anything the text names." in prompt
    assert "- Measure [value, name]: A quantity the text reports." in prompt


def test_the_word_the_prompt_uses_for_a_segment_is_an_option() -> None:
    assert "Read one page of a source" in run(segment="page")["client"].prompts[0]
    assert "Read one segment of a source" in run()["client"].prompts[0]
    assert PROMPT.count("{unit}") == 4


def test_a_malformed_statement_is_counted_and_the_rest_of_the_reply_survives() -> None:
    state = run(
        [
            {"type": "Thing", "fields": {}},
            "not a statement at all",
            {"type": "Thing", "fields": {"name": "noise"}, "quote": "noise"},
        ]
    )

    assert state["malformed"] == 2
    assert len(state["statements"]) == 1


def test_a_key_nobody_asked_for_is_ignored_rather_than_fatal() -> None:
    state = run([{"type": "Thing", "fields": {}, "quote": "noise", "page": 1}])

    assert (state["malformed"], len(state["statements"])) == (0, 1)
    assert state["statements"][0].segment == 1


def test_the_reply_schema_offers_the_type_names_and_forbids_extra_keys() -> None:
    reply_schema = build_schema(SCHEMA)
    item = reply_schema["properties"][STATEMENTS]["items"]

    assert reply_schema["additionalProperties"] is False
    assert item["additionalProperties"] is False
    assert set(item["properties"]["type"]["enum"]) == SCHEMA.type_names()
    assert item["required"] == ["type", "fields", "quote"]
    assert item["properties"]["fields"]["additionalProperties"] == {"type": "string"}


def test_the_step_reports_what_it_spent_and_what_it_replayed() -> None:
    state = run(paid=1)

    # Two segments, so two calls; the second comes off the cache and is not charged again.
    assert (state["tokens"], state["cached_replies"]) == (10, 1)
