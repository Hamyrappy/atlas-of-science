"""Tests for the architectures on offer, and the standing checks every one of them must pass.

Two different things are under test here. The first is the catalogue itself: a manifest
is read into something an interface can show, and looked up by id or by number.

The second is the more valuable one. Every architecture in this library is a
configuration, so every architecture can be checked by reading it -- the packs load,
the steps exist, the options are ones those steps declare, and nothing reads a key that
is produced after it. Those checks run over all of them at once, which is what stops a
list of fifteen configurations from rotting one file at a time.

One of those checks is the library's own rule rather than a mechanical one: **an
architecture answers from a walked graph.** Its `ask` chain must contain a step that
produces a `bundle`, and it must end in a step that consumes one. That is
`docs/architectures/README.md` written as a test, and it is the check that would fail
first if somebody added an architecture that quietly answered from ranked text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas import catalogue
from atlas.llm import Reply
from atlas.ontology import load
from atlas.ontology.vocabulary import PROFILES
from atlas.pipeline import ASK, CHAIN, Pipeline
from atlas.reason import ENGINES, PROFILE_OF
from atlas.steps import get as step
from atlas.store.sqlite import SqliteStore
from conftest import Fixture

BUNDLE = "bundle"
ROOT = Path(__file__).parents[1]

ALL = catalogue.variants()


def test_the_catalogue_is_not_empty_and_is_ordered_by_number() -> None:
    assert ALL
    assert [one.number for one in ALL] == sorted(one.number for one in ALL)


def test_ids_and_numbers_are_unique() -> None:
    assert len({one.id for one in ALL}) == len(ALL)
    assert len({one.number for one in ALL}) == len(ALL)


def test_an_architecture_is_found_by_id_and_by_number() -> None:
    one = ALL[0]

    assert catalogue.get(one.id) == one
    assert catalogue.get(str(one.number)) == one


def test_an_unknown_architecture_is_refused_with_the_ones_that_exist() -> None:
    with pytest.raises(ValueError, match="unknown architecture"):
        catalogue.get("a99")


def test_a_manifest_without_a_variant_block_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("steps: [ingest_text]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="variant"):
        catalogue.read(path)


@pytest.mark.parametrize("variant", ALL, ids=lambda one: one.id)
def test_every_architecture_declares_what_an_interface_needs_to_show_it(
    variant: catalogue.Variant,
) -> None:
    assert variant.title and variant.summary and variant.mechanism
    assert variant.optimises and variant.cost
    assert variant.questions
    assert variant.steps and variant.ontologies
    assert variant.reasoning


@pytest.mark.parametrize("variant", ALL, ids=lambda one: one.id)
def test_every_architecture_loads_as_a_configuration(variant: catalogue.Variant) -> None:
    path = ROOT / "architectures" / variant.config

    built = Pipeline.from_config(path, chain=CHAIN)
    asked = Pipeline.from_config(path, chain=ASK)

    assert built.steps and asked.steps
    assert built.schema.version == load(*variant.ontologies, shapes=variant.shapes).version
    assert built.schema.profile == variant.profile


#: The profiles each engine is complete for. RDFS entailment is within every tractable
#: profile, so an engine complete for one is complete for it too.
COMPLETE = {
    "rdfs": {"RDFS"},
    "rl": {"RDFS", "RL"},
    "el": {"RDFS", "EL"},
    "ql": {"RDFS", "QL"},
    "dl": set(PROFILES),
    "shacl": set(PROFILES),
}


@pytest.mark.parametrize("variant", ALL, ids=lambda one: one.id)
def test_every_architecture_names_a_profile_and_runs_an_engine_for_it(
    variant: catalogue.Variant,
) -> None:
    """The ontology is the working layer: every architecture reasons with it, completely.

    An engine is complete for its own profile and for RDFS. The one sanctioned exception is
    the RL engine over data under a DL ontology: RL rules are sound for OWL 2 DL, what they
    cannot use is reported by name, and no other engine may run over data at all.
    """
    assert variant.profile in PROFILES
    assert variant.engines, f"{variant.id} runs no engine over its ontology"
    assert set(variant.engines) <= set(ENGINES)
    for engine in variant.engines:
        if engine == "rl" and variant.profile == "DL":
            continue
        assert variant.profile in COMPLETE[engine], (
            f"{variant.id} runs {engine}, which is not complete for OWL 2 {variant.profile}"
        )
    assert any(PROFILE_OF.get(engine) == variant.profile for engine in variant.engines), (
        f"{variant.id} names {variant.profile} and runs no engine made for it"
    )


@pytest.mark.parametrize("variant", ALL, ids=lambda one: one.id)
def test_every_architecture_answers_from_a_walked_graph(variant: catalogue.Variant) -> None:
    path = ROOT / "architectures" / variant.config
    asked = [name for name, _ in _named(path)]

    builds = [name for name in asked if BUNDLE in step(name).produces]
    consumes = [name for name in asked if BUNDLE in step(name).requires]

    assert builds, f"{variant.id} answers without building an evidence package"
    assert consumes, f"{variant.id} builds a package and answers from something else"
    assert asked.index(builds[0]) < asked.index(consumes[-1])


@pytest.mark.parametrize("variant", ALL, ids=lambda one: one.id)
def test_every_architecture_has_the_specification_it_names(variant: catalogue.Variant) -> None:
    assert variant.spec
    assert (ROOT / variant.spec).is_file()


class StubClient:
    """A client replying with one sentence citing the first thing it was shown."""

    def complete(self, prompt: str, *, schema: dict | None = None,
                 system: str | None = None) -> Reply:
        ref = next((word.strip("[]") for word in prompt.split() if word.startswith("[")), "")
        return Reply(text=f"It holds under U1. [{ref}]", usage={}, cached=True)

    def complete_json(self, prompt: str, schema: dict, *, system: str | None = None) -> dict:
        raise AssertionError("no step of an ask chain here should need structured output")


@pytest.mark.parametrize("variant", ALL, ids=lambda one: one.id)
def test_every_architecture_answers_a_question_over_a_small_store(
    variant: catalogue.Variant, science: Fixture, tmp_path: Path,
) -> None:
    """The whole `ask` chain, run: the engines it names execute over a real store.

    `federate` is left out, since what it reads is somebody else's registry; the store it
    would build is the fixture's, and nothing it publishes is needed by the rest. An
    architecture that names a relational store gets the fixture copied into one.
    """
    asked = Pipeline.from_config(ROOT / "architectures" / variant.config, chain=ASK)
    pipeline = Pipeline(asked.schema, tuple(one for one in asked.steps
                                            if one[0].name != "federate"))
    store = science.store
    if isinstance(asked.store, SqliteStore):
        store = SqliteStore(tmp_path / "atlas.db")
        for source in science.store.sources():
            store.add_source(source)
        for assertion in science.store.assertions():
            store.assert_(assertion)

    state = pipeline.run_state(pipeline.initial(
        store=store, question="Did treatment M raise the measured yield under U1?",
        client=StubClient(), origins={},
    ))

    assert state["bundle"].grounded, f"{variant.id} walked nothing over the fixture"
    assert "answer" in state
    if "entail" in variant.ask:
        assert state["closure_finished"]


@pytest.mark.parametrize("variant", ALL, ids=lambda one: one.id)
def test_every_gate_on_the_ontology_passes_for_the_ontology_shipped(
    variant: catalogue.Variant,
) -> None:
    """The steps of the build chain that read only the ontology -- the formal gate, the
    classifier -- run strict before anything is written, so the shipped ontologies have to
    pass them, with the engine each architecture names."""
    built = Pipeline.from_config(ROOT / "architectures" / variant.config, chain=CHAIN)
    state = {"schema": built.schema}
    for one, options in built.steps:
        if set(one.requires) <= {"schema"}:
            state |= one(state, options)


def test_the_table_shows_one_architecture_per_pair_of_lines() -> None:
    rendered = catalogue.table()

    assert len(rendered.splitlines()) == 2 * len(ALL)
    assert ALL[0].title in rendered


def _named(path: Path) -> list[tuple[str, object]]:
    """The `ask` chain of a manifest, as the pipeline resolves it, with the names kept."""
    pipeline = Pipeline.from_config(path, chain=ASK)
    return [(one.name, options) for one, options in pipeline.steps]
