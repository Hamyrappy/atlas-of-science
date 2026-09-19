"""Tests for the pool of words the pack has no room for, and for the gate one has to pass.

The three decisions the module states are the three under test: support counts
independent source families rather than mentions, a word the schema already has is
reported as a reuse rather than minted a second time, and every refusal carries the
gate it failed. The fourth thing under test is that nothing promotes itself -- what
comes out is a pack fragment for somebody to read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.model import Schema, Segment, Source, TypeDef
from atlas.steps.induce import (
    Candidate,
    InduceOptions,
    PromoteOptions,
    induce,
    pack,
    promote,
    similarity,
)
from atlas.steps.relocate import Statement
from atlas.store.jsonl import JsonlStore

SCHEMA = Schema(version="0" * 12, types=(TypeDef(name="Study", description="An investigation."),))
DEFAULTS = InduceOptions()
GATE = PromoteOptions()


def source(source_id: str, **meta: str) -> Source:
    return Source(id=source_id, origin=f"{source_id}.txt",
                  segments=(Segment(number=1, text="a line of text\n"),), meta=meta)


def statement(source_id: str, type_name: str, quote: str = "a line of text") -> Statement:
    return Statement(source_id=source_id, segment=1, type=type_name, quote=quote)


def state(*statements: Statement, sources: tuple[Source, ...] = (), store: object = None) -> dict:
    held = sources or tuple(source(one.source_id) for one in statements)
    seen: dict[str, Source] = {one.id: one for one in held}
    made = {"statements": statements, "schema": SCHEMA, "sources": tuple(seen.values())}
    return made if store is None else made | {"store": store}


def test_a_known_type_never_reaches_the_pool() -> None:
    result = induce(state(statement("a", "Study")), DEFAULTS)

    assert result["candidates"] == ()


def test_an_unknown_type_is_pooled_with_the_sources_it_came_from() -> None:
    result = induce(state(statement("a", "Calibration"), statement("b", "Calibration")), DEFAULTS)

    [candidate] = result["candidates"]
    assert candidate.label == "Calibration"
    assert candidate.support == 2
    assert candidate.families == ("a", "b")


def test_ten_mentions_in_one_source_are_one_family() -> None:
    many = [statement("a", "Calibration", f"line {n}") for n in range(10)]

    [candidate] = induce(state(*many), DEFAULTS)["candidates"]

    assert candidate.support == 1


def test_a_family_can_be_something_the_corpus_knows_better_than_a_file() -> None:
    sources = (source("a", venue="One"), source("b", venue="One"), source("c", venue="Two"))
    statements = (statement("a", "Calibration"), statement("b", "Calibration"),
                  statement("c", "Calibration"))

    [candidate] = induce(
        state(*statements, sources=sources), InduceOptions(family_field="venue")
    )["candidates"]

    # Two venues, not three files: a group publishing twice is one family.
    assert candidate.families == ("One", "Two")


def test_labels_sharing_enough_terms_are_pooled_together() -> None:
    result = induce(
        state(statement("a", "calibration step"), statement("b", "calibration procedure step")),
        DEFAULTS,
    )

    [candidate] = result["candidates"]
    assert set(candidate.variants) == {"calibration step", "calibration procedure step"}
    # The shorter surface form is what a reader is shown.
    assert candidate.label == "calibration step"


def test_grouping_does_not_stem_and_the_module_says_so() -> None:
    # "step" and "steps" share no token, so overlap puts them at 1/3 and the default
    # threshold separates them. Crude, documented, and visible here rather than later.
    result = induce(
        state(statement("a", "calibration step"), statement("b", "calibration steps")), DEFAULTS
    )

    assert len(result["candidates"]) == 2


def test_every_candidate_carries_the_closest_term_the_schema_already_has() -> None:
    [candidate] = induce(state(statement("a", "Study design")), DEFAULTS)["candidates"]

    assert candidate.nearest == "Study"
    assert candidate.similarity == pytest.approx(0.5)


def test_the_gate_refuses_thin_support_and_says_so() -> None:
    thin = Candidate(term="c", label="Calibration", families=("a",), definition="a thing, new",
                     rounds=9)

    result = promote({"candidates": (thin,), "schema": SCHEMA}, GATE)

    assert result["promoted"] == ()
    assert "support 1 in independent families" in result["refused"][0].reason


def test_the_gate_refuses_a_word_seen_in_only_one_round() -> None:
    fresh = Candidate(term="c", label="Calibration", families=("a", "b", "c"),
                      definition="a thing, new", rounds=1)

    result = promote({"candidates": (fresh,), "schema": SCHEMA}, GATE)

    assert "seen in 1 round(s)" in result["refused"][0].reason


def test_the_gate_refuses_a_word_with_no_definition() -> None:
    silent = Candidate(term="c", label="Calibration", families=("a", "b", "c"), rounds=2)

    result = promote({"candidates": (silent,), "schema": SCHEMA}, GATE)

    assert "no definition" in result["refused"][0].reason


def test_the_gate_sends_a_near_duplicate_back_to_the_term_that_exists() -> None:
    duplicate = Candidate(term="c", label="Study", families=("a", "b", "c"), rounds=2,
                          definition="an investigation, carried out", nearest="Study",
                          similarity=1.0)

    result = promote({"candidates": (duplicate,), "schema": SCHEMA}, GATE)

    assert "reuse 'Study' instead" in result["refused"][0].reason


def test_a_candidate_that_passes_everything_becomes_a_proposal_and_not_a_type() -> None:
    ready = Candidate(term="c", label="Calibration", families=("a", "b", "c"), rounds=2,
                      definition="a preparation step, performed before measurement")

    result = promote({"candidates": (ready,), "schema": SCHEMA}, PromoteOptions(parent="Study"))

    assert [one.label for one in result["promoted"]] == ["Calibration"]
    assert "name: Calibration" in result["proposal"]
    assert "parent: Study" in result["proposal"]
    # The loaded schema is untouched: a proposal is a file, not an edit.
    assert SCHEMA.find_type("Calibration") is None


def test_a_proposal_of_nothing_is_empty_rather_than_an_empty_pack() -> None:
    assert pack(()) == ""


def test_the_pool_is_kept_across_rounds_so_stability_means_two_runs(tmp_path: Path) -> None:
    store = JsonlStore(tmp_path / "store")
    first = induce(state(statement("a", "Calibration"), store=store), DEFAULTS)
    second = induce(state(statement("b", "Calibration"), store=store), DEFAULTS)

    assert first["candidates"][0].rounds == 1
    assert second["candidates"][0].rounds == 2
    # The families accumulate too: the second run saw one source and knows about two.
    assert second["candidates"][0].families == ("a", "b")


def test_a_truncated_registry_is_an_empty_pool_rather_than_a_failed_run(tmp_path: Path) -> None:
    store = JsonlStore(tmp_path / "store")
    path = store.artifact("candidates.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ truncated", encoding="utf-8")

    result = induce(state(statement("a", "Calibration"), store=store), DEFAULTS)

    assert result["candidates"][0].rounds == 1


def test_similarity_is_symmetric_and_knows_nothing_about_either_word() -> None:
    assert similarity("calibration step", "step calibration") == 1.0
    assert similarity("calibration", "") == 0.0
