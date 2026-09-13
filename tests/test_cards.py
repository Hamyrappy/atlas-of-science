"""Tests for card extraction, driven by a stub client that returns canned replies."""

from __future__ import annotations

from atlas.contracts import Document, Page
from atlas.extract.cards import STATEMENTS, ExtractionResult, build_schema, extract_cards
from atlas.ontology import load, validate_card

METHOD_QUOTE = "We introduce a wavelet prior that is fitted once and reused at inference time."
RESULT_QUOTE = "On the held-out split the error falls to 0.12, against 0.19 for the baseline."
PAGE_ONE = (
    f"1 Introduction\nRecovering a clean signal from noise is an open task.\n{METHOD_QUOTE}\n"
)
PAGE_TWO = f"2 Results\n{RESULT_QUOTE}\n"

DOCUMENT = Document(
    id="doc-1",
    source="fixtures/doc-1.pdf",
    pages=(Page(number=1, text=PAGE_ONE), Page(number=2, text=PAGE_TWO)),
)
ONTOLOGY = load()


class FakeClient:
    """A client stub with the signature of `complete_json`, replaying canned replies."""

    def __init__(self, *replies: list[dict]) -> None:
        self.replies = [{STATEMENTS: reply} for reply in replies]
        self.prompts: list[str] = []

    def complete_json(self, prompt: str, schema: dict, *, system: str | None = None) -> dict:
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else {STATEMENTS: []}


def statement(type_name: str, fields: dict[str, str], quote: str, page: int = 1) -> dict:
    return {"type": type_name, "fields": fields, "quote": quote, "page": page}


def method(quote: str = METHOD_QUOTE) -> dict:
    return statement("Method", {"name": "wavelet prior", "summary": "fitted once"}, quote)


def result_card() -> dict:
    return statement("Result", {"statement": "error falls", "value": "0.12"}, RESULT_QUOTE, 2)


def run(*replies: list[dict], run_id: str = "run-1") -> ExtractionResult:
    return extract_cards(DOCUMENT, ONTOLOGY, FakeClient(*replies), run_id=run_id)


def test_a_well_formed_reply_becomes_cards_bound_to_their_quotes() -> None:
    extracted = run([method()], [result_card()])

    assert (extracted.dropped, extracted.needs_review) == (0, 0)
    assert [card.type for card in extracted.cards] == ["Method", "Result"]
    for card in extracted.cards:
        span = card.spans[0]
        assert DOCUMENT.page_text(span.page)[span.start : span.end] == span.text
        assert card.run_id == "run-1"
        assert card.ontology_version == ONTOLOGY.version
    assert extracted.cards[0].spans[0].text == METHOD_QUOTE


def test_one_call_per_page_with_the_page_text_in_the_prompt() -> None:
    client = FakeClient([method()], [result_card()])
    extract_cards(DOCUMENT, ONTOLOGY, client, run_id="run-1")

    assert len(client.prompts) == 2
    assert PAGE_ONE in client.prompts[0]
    assert PAGE_TWO in client.prompts[1]
    assert "Method" in client.prompts[0]


def test_only_the_requested_pages_are_read_and_the_span_lands_where_the_quote_is() -> None:
    # The reply claims page 1; the card must carry the page the quote was found on.
    client = FakeClient([statement("Result", {"value": "0.12"}, RESULT_QUOTE, page=1)])
    extracted = extract_cards(DOCUMENT, ONTOLOGY, client, run_id="run-1", pages=[2])

    assert len(client.prompts) == 1
    assert extracted.cards[0].spans[0].page == 2


def test_an_invented_quote_is_dropped_and_counted() -> None:
    extracted = run([method("Our transformer was trained on eight million documents.")])

    assert extracted.cards == ()
    assert extracted.dropped == 1


def test_an_unknown_type_is_rejected_and_counted() -> None:
    extracted = run([statement("Instrument", {"name": "a spectrometer"}, METHOD_QUOTE)])

    assert extracted.cards == ()
    assert extracted.dropped == 1


def test_a_field_the_type_does_not_declare_is_rejected_and_counted() -> None:
    extracted = run([statement("Method", {"accuracy": "0.9"}, METHOD_QUOTE)])

    assert extracted.cards == ()
    assert extracted.dropped == 1


def test_a_malformed_statement_is_counted_without_reaching_relocation() -> None:
    extracted = run([{"type": "Method", "fields": {}}, method()])

    assert extracted.dropped == 1
    assert len(extracted.cards) == 1


def test_an_inexact_quote_is_placed_but_flagged_for_review() -> None:
    extracted = run([method(METHOD_QUOTE.replace("wavelet", "wavlet"))])

    assert extracted.needs_review == 1
    span = extracted.cards[0].spans[0]
    assert DOCUMENT.page_text(span.page)[span.start : span.end] == span.text
    assert "wavelet prior" in span.text


def test_ids_are_stable_across_runs_and_identify_one_card() -> None:
    first = run([method()], [result_card()])
    second = run([method()], [result_card()], run_id="run-2")
    twice = run([method()], [method()])

    assert [card.id for card in first.cards] == [card.id for card in second.cards]
    assert len({card.id for card in first.cards}) == 2
    assert len(twice.cards) == 1


def test_produced_cards_validate_against_the_core_ontology() -> None:
    extracted = run([method()], [result_card()])

    assert extracted.cards
    for card in extracted.cards:
        assert validate_card(card, ONTOLOGY) == []


def test_the_schema_offers_the_ontology_types_and_forbids_extra_keys() -> None:
    schema = build_schema(ONTOLOGY)
    item = schema["properties"][STATEMENTS]["items"]

    assert schema["additionalProperties"] is False
    assert item["additionalProperties"] is False
    assert set(item["properties"]["type"]["enum"]) == ONTOLOGY.type_names()
    assert item["required"] == ["type", "fields", "quote", "page"]
    assert item["properties"]["page"]["type"] == "integer"
    assert item["properties"]["fields"]["additionalProperties"] == {"type": "string"}


def test_two_statements_sharing_a_quote_both_survive() -> None:
    """One sentence can carry two results; hashing the quote alone lost the second."""
    client = FakeClient(
        [
            statement("Result", {"statement": "held-out error", "value": "0.12"}, RESULT_QUOTE, 2),
            statement("Result", {"statement": "baseline error", "value": "0.19"}, RESULT_QUOTE, 2),
        ]
    )

    result = extract_cards(DOCUMENT, ONTOLOGY, client, run_id="r1", pages=[2])

    assert len(result.cards) == 2
    assert len({card.id for card in result.cards}) == 2
    assert result.dropped == 0
