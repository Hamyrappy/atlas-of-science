"""Tests for the step that asks a model for relations, driven by a stub client.

The schema here is invented for the test, as in `test_extract_llm` and for the same
reason: the step reads the relations on offer out of whichever schema it is given. The
source has one segment holding two nodes, one holding a single node and one holding two
more, because which segments are asked about at all is half of what the step decides.
"""

from __future__ import annotations

from atlas.llm import Reply
from atlas.model import FieldDef, Node, PredicateDef, Schema, Segment, Source, Span, TypeDef
from atlas.steps import get
from atlas.steps.relate import relate
from atlas.steps.relate_llm import (
    PROMPT,
    RELATIONS,
    RelateLlmOptions,
    build_schema,
    relate_llm,
)

FIRST = "The pressure gauge recorded the tide at the northern pier.\n"
SECOND = "A second gauge was kept in reserve.\n"
THIRD = "The surge was measured with the reserve gauge after the storm.\n"

SOURCE = Source(
    id="notes",
    origin="notes.txt",
    segments=(Segment(number=1, text=FIRST), Segment(number=2, text=SECOND),
              Segment(number=3, text=THIRD)),
)

SCHEMA = Schema(
    version="a1b2c3d4e5f6",
    types=(
        TypeDef(
            name="Observation",
            fields=(FieldDef(name="subject"),),
            label_field="subject",
            description="Something recorded as having happened.",
        ),
        TypeDef(
            name="Instrument",
            fields=(FieldDef(name="name"),),
            label_field="name",
            description="A device a recording was taken with.",
        ),
    ),
    predicates=(
        PredicateDef(
            name="recorded_with",
            domain="Observation",
            range="Instrument",
            description="The observation was taken with this instrument.",
        ),
        PredicateDef(name="same_as", description="Both name one thing."),
    ),
)


def node(node_id: str, type_name: str, segment: int, quote: str, **fields: str) -> Node:
    start = SOURCE.segment_text(segment).index(quote)
    return Node(
        id=node_id,
        type=type_name,
        fields=fields,
        spans=(Span.of(SOURCE, segment, start, start + len(quote)),),
        schema_version=SCHEMA.version,
    )


TIDE = node("1" * 16, "Observation", 1, "recorded the tide", subject="tide")
GAUGE = node("2" * 16, "Instrument", 1, "The pressure gauge", name="pressure gauge")
SPARE = node("3" * 16, "Instrument", 2, "A second gauge", name="second gauge")
SURGE = node("4" * 16, "Observation", 3, "The surge", subject="surge")
RESERVE = node("5" * 16, "Instrument", 3, "the reserve gauge", name="reserve gauge")
NODES = (TIDE, GAUGE, SPARE, SURGE, RESERVE)


class FakeClient:
    """A client stub with the signature of `complete_json`, replaying canned replies.

    A reply is the list a model would put under the key, or a whole body when a test is
    about a body that has no such list. Every reply is charged for 10 tokens; the ones
    beyond `paid` come back marked cached, as in `test_extract_llm`.
    """

    def __init__(self, *replies: list | dict, paid: int = 99) -> None:
        self.replies = [reply if isinstance(reply, dict) else {RELATIONS: reply}
                        for reply in replies]
        self.prompts: list[str] = []
        self.schemas: list[dict] = []
        self.paid = paid

    def complete_json(self, prompt: str, schema: dict, *,
                      system: str | None = None) -> tuple[dict, Reply]:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        body = self.replies.pop(0) if self.replies else {RELATIONS: []}
        cached = len(self.prompts) > self.paid
        return body, Reply(text="", usage={"total_tokens": 10}, cached=cached)


def run(*replies: list | dict, paid: int = 99, nodes: tuple[Node, ...] = NODES,
        **options: str) -> dict:
    client = FakeClient(*replies, paid=paid)
    state = relate_llm(
        {"sources": (SOURCE,), "nodes": nodes, "schema": SCHEMA, "client": client},
        RelateLlmOptions(**options),
    )
    return state | {"client": client}


def claimed(src: Node, dst: Node, quote: str, predicate: str = "recorded_with") -> dict:
    return {"predicate": predicate, "src_ref": src.ref, "dst_ref": dst.ref, "quote": quote}


def test_a_reply_becomes_relations_bound_to_the_segment_they_were_read_from() -> None:
    state = run(
        [claimed(TIDE, GAUGE, "The pressure gauge recorded the tide")],
        [claimed(SURGE, RESERVE, "measured with the reserve gauge")],
    )

    assert state["malformed_relations"] == 0
    assert [(r.predicate, r.source_id, r.segment) for r in state["relations"]] == [
        ("recorded_with", SOURCE.id, 1), ("recorded_with", SOURCE.id, 3)]
    assert (state["relations"][0].src_ref, state["relations"][0].dst_ref) == (TIDE.ref, GAUGE.ref)
    assert state["relations"][1].quote == "measured with the reserve gauge"


def test_only_a_segment_holding_two_nodes_or_more_is_asked_about() -> None:
    prompts = run()["client"].prompts

    # The second segment holds one node, and one thing cannot be related to anything.
    assert len(prompts) == 2
    assert FIRST in prompts[0]
    assert THIRD in prompts[1]
    assert not any(SECOND in prompt for prompt in prompts)


def test_no_call_is_made_when_no_segment_holds_a_pair() -> None:
    state = run(nodes=(TIDE, SPARE, RESERVE))

    assert state["client"].prompts == []
    assert (state["relations"], state["malformed_relations"]) == ((), 0)
    assert (state["tokens"], state["cached_replies"]) == (0, 0)


def test_the_prompt_offers_the_relations_of_the_loaded_schema_with_what_they_connect() -> None:
    prompt = run()["client"].prompts[0]

    assert ("- recorded_with (Observation -> Instrument): "
            "The observation was taken with this instrument.") in prompt
    assert "- same_as (owl:Thing -> owl:Thing): Both name one thing." in prompt


def test_the_prompt_offers_the_nodes_of_that_segment_alone_under_their_references() -> None:
    first, third = run()["client"].prompts

    assert f"- {TIDE.ref} (Observation): tide" in first
    assert f"- {GAUGE.ref} (Instrument): pressure gauge" in first
    assert f"- {SURGE.ref} (Observation): surge" in third
    # Nodes of other segments are not on offer: a relation across two is not asked for.
    assert SPARE.ref not in first and RESERVE.ref not in first
    assert TIDE.ref not in third and SPARE.ref not in third


def test_the_word_the_prompt_uses_for_a_segment_is_an_option() -> None:
    assert "Read one page of a source" in run(segment="page")["client"].prompts[0]
    assert "page 3:" in run(segment="page")["client"].prompts[1]
    assert "Read one segment of a source" in run()["client"].prompts[0]
    assert PROMPT.count("{unit}") == 6


def test_a_malformed_relation_is_counted_and_the_rest_of_the_reply_survives() -> None:
    state = run(
        [
            {"predicate": "recorded_with", "src_ref": TIDE.ref, "dst_ref": GAUGE.ref},
            "not a relation at all",
            claimed(TIDE, GAUGE, "recorded the tide"),
        ]
    )

    assert state["malformed_relations"] == 2
    assert [r.quote for r in state["relations"]] == ["recorded the tide"]


def test_a_key_nobody_asked_for_is_ignored_rather_than_fatal() -> None:
    state = run([claimed(TIDE, GAUGE, "recorded the tide") | {"confidence": 0.9, "segment": 7}])

    assert (state["malformed_relations"], len(state["relations"])) == (0, 1)
    # Where a relation was read is the step's to say, whatever the reply volunteers.
    assert state["relations"][0].segment == 1


def test_a_body_without_the_list_yields_nothing_and_counts_nothing() -> None:
    state = run({}, {RELATIONS: "none found"})

    assert len(state["client"].prompts) == 2
    assert (state["relations"], state["malformed_relations"]) == ((), 0)


def test_an_endpoint_the_model_invents_is_passed_on_for_relate_to_drop() -> None:
    """The step does not resolve references; it hands them over, and `relate` refuses them."""
    state = run([
        claimed(TIDE, GAUGE, "The pressure gauge recorded the tide"),
        claimed(TIDE, GAUGE, "recorded the tide") | {"dst_ref": "notes:nowhere"},
    ])

    assert [r.dst_ref for r in state["relations"]] == [GAUGE.ref, "notes:nowhere"]

    placed = relate({"sources": (SOURCE,), "nodes": NODES, "schema": SCHEMA,
                     "relations": state["relations"]})

    assert [(link.src, link.dst) for link in placed["links"]] == [(TIDE.id, GAUGE.id)]
    assert placed["unrelated"] == 1


def test_the_reply_schema_offers_the_predicate_names_and_forbids_extra_keys() -> None:
    reply_schema = build_schema(SCHEMA)
    item = reply_schema["properties"][RELATIONS]["items"]

    assert reply_schema["additionalProperties"] is False
    assert reply_schema["required"] == [RELATIONS]
    assert item["additionalProperties"] is False
    assert item["properties"]["predicate"]["enum"] == ["recorded_with", "same_as"]
    assert item["required"] == ["predicate", "src_ref", "dst_ref", "quote"]
    assert run()["client"].schemas == [reply_schema, reply_schema]


def test_the_step_reports_what_it_spent_and_what_it_replayed() -> None:
    state = run(paid=1)

    # Two segments are asked about; the second comes off the cache and is not charged again.
    assert (state["tokens"], state["cached_replies"]) == (10, 1)


def test_the_step_declares_what_it_reads_what_it_adds_and_what_it_takes() -> None:
    step = get("relate_llm")

    assert step.requires == ("sources", "nodes", "schema", "client")
    assert step.produces == ("relations", "malformed_relations", "tokens", "cached_replies")
    assert step.options is RelateLlmOptions
    assert RelateLlmOptions().segment == "segment"
