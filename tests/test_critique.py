"""Tests for the deterministic critics and for the bounded repair that acts on them.

The critics are tested one at a time, because a critic that fires on everything is as
useless as one that fires on nothing. The repair loop is tested for the property that
makes it safe: an exhausted budget quarantines, and quarantine is never acceptance.
"""

from __future__ import annotations

from atlas.llm import Reply
from atlas.model import FieldDef, Node, Schema, Segment, Source, Span, TypeDef
from atlas.steps.critique import CritiqueOptions, critique, repairable
from atlas.steps.relocate import Statement, relocate
from atlas.steps.repair import RepairOptions, repair_llm

TEXT = "No increase in the measured yield was observed in the second series.\n"
SOURCE = Source(id="paper", origin="paper.txt", segments=(Segment(number=1, text=TEXT),))
SCHEMA = Schema(
    version="0" * 12,
    types=(TypeDef(name="Finding", fields=(FieldDef(name="statement"), FieldDef(name="value")),
                   label_field="statement"),),
)
DEFAULTS = CritiqueOptions()


def node(quote: str, **fields: str) -> Node:
    start = TEXT.index(quote)
    return Node(id="n" * 16, type="Finding", fields=fields,
                spans=(Span.of(SOURCE, 1, start, start + len(quote)),),
                schema_version=SCHEMA.version)


def findings(one: Node, options: CritiqueOptions = DEFAULTS) -> dict[str, str]:
    result = critique({"nodes": (one,), "schema": SCHEMA}, options)
    return {found.check: found.detail for found in result["findings"]}


def test_a_well_formed_node_draws_nothing() -> None:
    good = node("increase in the measured yield", statement="the yield increased")

    assert findings(good) == {}


def test_a_type_the_pack_does_not_declare_is_reported() -> None:
    unknown = node("increase in the measured yield", statement="x").model_copy(
        update={"type": "Invented"}
    )

    assert "untyped" in findings(unknown)


def test_a_node_with_nothing_in_the_field_that_names_it_is_reported() -> None:
    unnamed = node("increase in the measured yield")

    assert "unnamed" in findings(unnamed)


def test_a_quote_too_short_to_stand_on_is_reported() -> None:
    thin = node("yield", statement="the yield increased")

    assert "thin" in findings(thin)


def test_a_field_that_does_not_appear_in_its_own_quote_is_reported() -> None:
    invented = node("increase in the measured yield", statement="the pressure fell")

    found = findings(invented, CritiqueOptions(grounded_fields=("statement",)))
    assert "does not appear in the quote" in found["ungrounded"]


def test_a_field_that_does_appear_draws_nothing_even_folded() -> None:
    quoted = node("increase in the measured yield", statement="Measured Yield")

    assert findings(quoted, CritiqueOptions(grounded_fields=("statement",))) == {}


def test_the_negation_check_reports_and_does_not_judge() -> None:
    inverted = node("No increase in the measured yield", statement="the yield increased")

    found = findings(inverted, CritiqueOptions(negations=("no ",)))
    assert "check the claim was not inverted" in found["negation"]


def test_negation_markers_are_the_configuration_s_words_and_not_the_library_s() -> None:
    inverted = node("No increase in the measured yield", statement="the yield increased")

    # Nothing named, nothing found: the package holds no words of any language.
    assert "negation" not in findings(inverted)


def test_a_negation_is_not_something_asking_again_would_fix() -> None:
    inverted = node("No increase in the measured yield", statement="the yield increased")
    result = critique({"nodes": (inverted,), "schema": SCHEMA},
                      CritiqueOptions(negations=("no ",)))

    assert repairable(result["findings"]) == ()


class StubClient:
    def __init__(self, *bodies: dict) -> None:
        self.bodies = list(bodies)
        self.calls = 0

    def complete(self, prompt: str, *, schema: dict | None = None,
                 system: str | None = None) -> Reply:
        raise AssertionError("repair asks for JSON, not prose")

    def complete_json(self, prompt: str, schema: dict, *,
                      system: str | None = None) -> tuple[dict, Reply]:
        self.calls += 1
        body = self.bodies.pop(0) if self.bodies else {"statement": {"withdraw": True}}
        return body, Reply(text="", usage={}, cached=False)


def repair_state(one: Node, options: CritiqueOptions, client: StubClient) -> dict:
    return {
        "nodes": (one,),
        "findings": critique({"nodes": (one,), "schema": SCHEMA}, options)["findings"],
        "sources": (SOURCE,),
        "schema": SCHEMA,
        "client": client,
    }


def corrected(**fields: str) -> dict:
    return {"statement": {"type": "Finding", "fields": fields,
                          "quote": "No increase in the measured yield", "withdraw": False}}


def test_a_repairable_node_goes_back_to_the_model_and_comes_back_as_a_statement() -> None:
    wrong = node("increase in the measured yield", statement="the pressure fell")
    client = StubClient(corrected(statement="no increase in the yield"))

    result = repair_llm(repair_state(wrong, CritiqueOptions(grounded_fields=("statement",)),
                                     client), RepairOptions())

    assert result["repaired"] == 1
    [statement] = result["statements"]
    assert statement.fields == {"statement": "no increase in the yield"}
    assert result["quarantined"] == ()


def test_a_node_nothing_was_said_against_comes_back_as_the_claim_it_was_made_from() -> None:
    good = node("increase in the measured yield", statement="the yield increased")
    client = StubClient()

    result = repair_llm(repair_state(good, DEFAULTS, client), RepairOptions())

    [statement] = result["statements"]
    assert (statement.type, statement.fields) == (good.type, good.fields)
    assert statement.quote == good.spans[0].text
    assert client.calls == 0


def test_an_untouched_node_re_placed_hashes_to_the_id_it_already_had() -> None:
    # Placed for real first, so the id under test is the content hash a run would
    # actually write, and not one this file made up.
    first = relocate({
        "sources": (SOURCE,), "schema": SCHEMA,
        "statements": (Statement(source_id=SOURCE.id, segment=1, type="Finding",
                                 fields={"statement": "the yield increased"},
                                 quote="increase in the measured yield"),),
    })
    [placed] = first["nodes"]

    result = repair_llm(repair_state(placed, DEFAULTS, StubClient()), RepairOptions())
    again = relocate({"sources": (SOURCE,), "statements": result["statements"],
                      "schema": SCHEMA})

    assert [one.id for one in again["nodes"]] == [placed.id]


def test_a_withdrawal_quarantines_rather_than_asserting_or_discarding() -> None:
    wrong = node("increase in the measured yield", statement="the pressure fell")
    client = StubClient({"statement": {"withdraw": True}})

    result = repair_llm(repair_state(wrong, CritiqueOptions(grounded_fields=("statement",)),
                                     client), RepairOptions())

    [held] = result["quarantined"]
    assert held.node is wrong
    assert [one.check for one in held.findings] == ["ungrounded"]
    assert result["repaired"] == 0


def test_an_exhausted_budget_quarantines_and_never_accepts() -> None:
    wrong = node("increase in the measured yield", statement="the pressure fell")
    client = StubClient({"statement": "not an object"}, {"statement": "not an object"},
                        {"statement": "not an object"})

    result = repair_llm(repair_state(wrong, CritiqueOptions(grounded_fields=("statement",)),
                                     client), RepairOptions(rounds=2))

    assert client.calls == 2
    assert len(result["quarantined"]) == 1
    assert result["quarantined"][0].rounds == 2
    assert result["statements"] == ()
