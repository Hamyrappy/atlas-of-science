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
from atlas.ontology import load
from atlas.pipeline import ASK, CHAIN, Pipeline
from atlas.steps import get as step

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
    assert variant.steps and variant.packs


@pytest.mark.parametrize("variant", ALL, ids=lambda one: one.id)
def test_every_architecture_loads_as_a_configuration(variant: catalogue.Variant) -> None:
    path = ROOT / "architectures" / variant.config

    built = Pipeline.from_config(path, chain=CHAIN)
    asked = Pipeline.from_config(path, chain=ASK)

    assert built.steps and asked.steps
    assert built.schema.version == load(*variant.packs).version


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


def test_the_table_shows_one_architecture_per_pair_of_lines() -> None:
    rendered = catalogue.table()

    assert len(rendered.splitlines()) == 2 * len(ALL)
    assert ALL[0].title in rendered


def _named(path: Path) -> list[tuple[str, object]]:
    """The `ask` chain of a manifest, as the pipeline resolves it, with the names kept."""
    pipeline = Pipeline.from_config(path, chain=ASK)
    return [(one.name, options) for one, options in pipeline.steps]
