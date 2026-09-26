"""Tests for reading a claim's form, and for refusing to reason over one that is unclear.

The claim the module makes is that three sentences which look alike are three different
claims, so the first test is that they come out as three different units. The rule worth
arguing about is tested twice: an unknown polarity is `unsupported` and not `lossy`,
because a claim whose negation scope nobody recorded can mean either of two opposite
things, while an unstated quantifier is merely lossy.
"""

from __future__ import annotations

from atlas.model import Agent, Assertion, Node, Schema, Segment, Source, Span
from atlas.ontology import load
from atlas.steps.graph_expand import Bundle
from atlas.steps.units import (
    CompileUnitsOptions,
    Unit,
    compile_units,
    judge,
    mark_units,
    provable_only,
    read,
)
from atlas.store.memory import MemoryStore

TEXT = (
    "Some samples show the effect.\n"
    "Samples usually show the effect.\n"
    "All samples show the effect.\n"
)
SOURCE = Source(id="paper", origin="paper.txt",
                segments=tuple(Segment(number=n, text=line)
                               for n, line in enumerate(TEXT.splitlines(keepends=True), start=1)))
OPTIONS = CompileUnitsOptions(
    kinds=("existential", "statistical", "universal", "conditional"),
    quantifiers=("some", "most", "all"),
    polarities=("affirmative", "negative"),
    modalities=("assertoric",),
)


def unit_node(number: int, quote: str, **fields: str) -> Node:
    text = SOURCE.segment_text(number)
    start = text.index(quote)
    schema = load("science_core", "semantic_units")
    return Node(id=f"{number}" * 16, type="SemanticUnit", fields=fields,
                spans=(Span.of(SOURCE, number, start, start + len(quote)),),
                schema_version=schema.version)


def form(**fields: str) -> Unit:
    return read(unit_node(1, "Some samples", **fields), OPTIONS)


def test_three_sentences_that_look_alike_are_three_different_units() -> None:
    existential = form(kind="existential", quantifier="some", polarity="affirmative",
                       expression="some samples show the effect")
    statistical = form(kind="statistical", quantifier="most", polarity="affirmative",
                       expression="samples usually show the effect")
    universal = form(kind="universal", quantifier="all", polarity="affirmative",
                     expression="all samples show the effect")

    assert {existential.kind, statistical.kind, universal.kind} == {
        "existential", "statistical", "universal"
    }
    assert {existential.quantifier, statistical.quantifier, universal.quantifier} == {
        "some", "most", "all"
    }
    assert all(one.provable for one in (existential, statistical, universal))


def test_an_unknown_polarity_is_unsupported_rather_than_lossy() -> None:
    profile, reason = judge("universal", "all", "", "", OPTIONS)

    assert profile == "unsupported"
    assert "scope of any negation is unknown" in reason


def test_an_unstated_quantifier_is_only_lossy() -> None:
    profile, reason = judge("universal", "", "affirmative", "", OPTIONS)

    assert profile == "lossy"
    assert "quantifier" in reason


def test_a_polarity_the_run_does_not_read_is_unsupported() -> None:
    profile, _reason = judge("universal", "all", "hedged", "", OPTIONS)

    assert profile == "unsupported"


def test_a_kind_the_run_does_not_interpret_is_unsupported() -> None:
    profile, reason = judge("rhetorical", "all", "affirmative", "", OPTIONS)

    assert profile == "unsupported"
    assert "not one this run interprets" in reason


def test_a_modality_the_run_does_not_read_is_only_lossy() -> None:
    profile, _reason = judge("universal", "all", "affirmative", "probable", OPTIONS)

    assert profile == "lossy"


def test_with_nothing_configured_nothing_is_exact() -> None:
    profile, _reason = judge("universal", "all", "affirmative", "", CompileUnitsOptions())

    assert profile == "unsupported"


def test_a_unit_with_no_form_at_all_is_unsupported() -> None:
    assert form(expression="something").profile == "unsupported"


def store_with(*nodes: Node) -> tuple[MemoryStore, Schema]:
    schema = load("science_core", "semantic_units")
    store = MemoryStore()
    store.add_source(SOURCE)
    agent = Agent(id="run", kind="run")
    for index, node in enumerate(nodes):
        store.assert_(Assertion(id=f"a{index}", agent=agent,
                                at="2026-01-01T00:00:00+00:00", target=node))
    return store, schema


def test_the_step_reads_every_unit_of_the_store_and_reports_the_unreadable_ones() -> None:
    good = unit_node(3, "All samples", kind="universal", quantifier="all",
                     polarity="affirmative", expression="all samples show the effect")
    bad = unit_node(2, "Samples usually", kind="universal", expression="unclear")
    store, schema = store_with(good, bad)

    result = compile_units({"store": store, "schema": schema}, OPTIONS)

    assert len(result["units"]) == 2
    assert result["provable"] == (good.id,)
    assert result["unsupported_units"] == 1


def test_what_may_be_a_premise_is_only_what_is_exact() -> None:
    units = (
        Unit(node_id="a", profile="exact"),
        Unit(node_id="b", profile="lossy"),
        Unit(node_id="c", profile="unsupported"),
    )

    assert provable_only(units) == ("a",)


def test_the_package_carries_the_form_so_an_answer_can_use_it() -> None:
    node = unit_node(3, "All samples", kind="universal", quantifier="all",
                     polarity="affirmative", expression="all samples show the effect")
    bundle = Bundle(roots=(node.id,), nodes=(node,), reasons={node.id: "ranked 0.500"})
    units = (read(node, OPTIONS),)

    marked = mark_units({"bundle": bundle, "units": units})["bundle"]

    assert "ranked 0.500" in marked.reasons[node.id]
    assert "universal, all, affirmative" in marked.reasons[node.id]
    assert "exact" in marked.reasons[node.id]


def test_a_unit_that_may_not_be_reasoned_over_is_still_in_the_package() -> None:
    node = unit_node(2, "Samples usually", kind="universal", expression="unclear")
    bundle = Bundle(roots=(node.id,), nodes=(node,))
    units = (read(node, OPTIONS),)

    marked = mark_units({"bundle": bundle, "units": units})["bundle"]

    # Nothing is filtered: it is still what a source said, and dropping it would lose
    # the evidence along with the inference.
    assert marked.nodes == (node,)
    assert "unsupported" in marked.reasons[node.id]


# ---- an exact unit as OWL, judged by the EL engine ---------------------------------------

READ = OPTIONS.model_copy(update={
    "quantifiers": ("some", "most", "all", "none"),
    "readings": {"all": "all", "some": "some", "none": "none"},
    "negative": ("negative",),
})


def claim(number: int, subject: str, obj: str, quantifier: str = "all",
          polarity: str = "affirmative", kind: str = "universal") -> Node:
    quote = {1: "Some samples", 2: "Samples usually", 3: "All samples"}[number]
    node = unit_node(number, quote, kind=kind, quantifier=quantifier, polarity=polarity,
                     subject_term=subject, object_term=obj, expression=quote)
    # Distinct ids for several claims on one sentence.
    return node.model_copy(update={"id": f"{subject}-{obj}-{quantifier}-{polarity}"})


def units_of(*nodes: Node, options: CompileUnitsOptions = READ) -> dict:
    store, schema = store_with(*nodes)
    return compile_units({"store": store, "schema": schema}, options)


def by_id(result: dict) -> dict[str, Unit]:
    return {one.node_id: one for one in result["units"]}


def test_a_universal_claim_becomes_a_subclass_axiom_in_every_tractable_profile() -> None:
    node = claim(3, "samples", "measured things")

    unit = by_id(units_of(node))[node.id]

    assert unit.form == "subclass"
    assert unit.axiom == "SubClassOf(unit-term:samples unit-term:measured things)"
    assert {"EL", "QL", "RL"} <= set(unit.owl_profiles)
    assert unit.status == "consistent"


def test_a_term_the_ontology_has_a_class_for_is_that_class() -> None:
    node = claim(3, "StudyResult", "InformationEntity")

    unit = by_id(units_of(node))[node.id]

    assert unit.subject_class == "StudyResult"
    # The ontology already says so, and the step says the source only restated it.
    assert unit.status == "follows"


def test_two_universal_claims_that_leave_a_term_empty_contradict_each_other() -> None:
    every = claim(3, "samples", "stable")
    none = claim(3, "samples", "stable", quantifier="none")

    result = units_of(every, none)
    units = by_id(result)

    assert units[every.id].status == "contradicted"
    assert units[every.id].against == (none.id,)
    assert units[none.id].against == (every.id,)
    assert len(result["unit_conflicts"]) == 1
    assert "no possible member" in result["unit_conflicts"][0].detail


def test_a_contradiction_names_only_the_units_it_needs() -> None:
    every = claim(3, "samples", "stable")
    none = claim(3, "samples", "stable", quantifier="none")
    unrelated = claim(1, "methods", "published", quantifier="all")

    units = by_id(units_of(every, none, unrelated))

    assert units[every.id].against == (none.id,)
    assert units[unrelated.id].status == "consistent"


def test_an_existence_claim_is_checked_against_the_ontologys_disjointness_not_added() -> None:
    # The ontology makes processes and information entities disjoint, so "some study is a
    # dataset" is ruled out by the ontology itself -- and nothing is invented to make it true.
    node = claim(1, "Study", "Dataset", quantifier="some", kind="existential")

    result = units_of(node)
    unit = by_id(result)[node.id]

    assert unit.form == "exists"
    assert unit.owl_profiles == ()
    assert unit.status == "contradicted"
    assert unit.against == ()
    assert "the ontology rules out" in result["unit_conflicts"][0].detail


def test_a_negative_existence_claim_is_contradicted_by_a_universal_one() -> None:
    every = claim(3, "samples", "stable")
    some_not = claim(1, "samples", "stable", quantifier="some", polarity="negative",
                     kind="existential")

    units = by_id(units_of(every, some_not))

    assert units[some_not.id].form == "exists-not"
    assert units[some_not.id].status == "contradicted"
    assert units[some_not.id].against == (every.id,)


def test_a_quantifier_word_nobody_mapped_is_not_translated() -> None:
    node = claim(3, "samples", "stable", quantifier="most", kind="statistical")

    unit = by_id(units_of(node))[node.id]

    assert unit.provable
    assert unit.form == ""
    assert unit.axiom == ""
    assert unit.status == ""


def test_the_package_says_what_a_unit_is_as_owl_and_what_the_engine_concluded() -> None:
    every = claim(3, "samples", "stable")
    none = claim(3, "samples", "stable", quantifier="none")
    result = units_of(every, none)
    bundle = Bundle(roots=(every.id,), nodes=(every, none))

    marked = mark_units({"bundle": bundle, "units": result["units"]})["bundle"]

    assert "as OWL: SubClassOf(" in marked.reasons[every.id]
    assert f"contradicted together with {none.id}" in marked.reasons[every.id]
