"""The claim the library makes about itself: the core carries no vocabulary of its own.

Everything here runs under a pack invented for this file -- observations taken with
instruments, a domain the library has never seen -- through the steps the shipped
configuration names. Nothing in `atlas/` is patched, subclassed or forked to make it
work; if a line of this file needed a change under `atlas/`, the core knows a domain
it should not. The shipped pack is loaded nowhere in this module, and one test insists
that a type it declares is as unknown here as any other invented word.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.model import Agent, Assertion, Link, Node
from atlas.ontology import load
from atlas.pipeline import Pipeline
from atlas.store.memory import MemoryStore

PACK = """
prefixes:
  obs: https://example.org/ontology/observation#

types:
  - name: Observation
    iri: obs:Observation
    description: Something recorded as having happened, at a place and a time.
    fields: [subject, value]

  - name: Instrument
    iri: obs:Instrument
    description: A device a recording was taken with.
    fields: [name, calibration]

predicates:
  - name: recorded_with
    iri: obs:recordedWith
    domain: Observation
    range: Instrument
    description: The observation was taken with this instrument.
"""

STEPS = """\
  - ingest_pdf
  - {stub_extract: {types: {Observation: subject, Instrument: name}}}
  - relocate
  - validate
  - assert: {agent: run}
"""

LINES = (
    ("The tide rose by 0.4 metres between 03:00 and 04:00.", "The sky stayed clear."),
    ("A pressure gauge logged the reading every minute.",),
)


@pytest.fixture
def pdf(build_pdf: Callable[..., bytes], tmp_path: Path) -> Path:
    path = tmp_path / "field-notes.pdf"
    path.write_bytes(build_pdf(LINES))
    return path


@pytest.fixture
def run(pdf: Path, write_config: Callable[[str, str], Path]) -> dict:
    store = MemoryStore()
    return Pipeline.from_config(write_config(PACK, STEPS)).run([pdf], store=store)


def test_the_core_ships_no_vocabulary_and_the_run_holds_only_the_invented_one(run: dict) -> None:
    assert load().types == ()
    assert run["schema"].type_names() == {"Observation", "Instrument"}


def test_nodes_of_the_invented_types_come_out_valid_and_located(run: dict) -> None:
    schema, source = run["schema"], run["sources"][0]

    assert run["violations"] == ()
    assert {node.type for node in run["nodes"]} == {"Observation", "Instrument"}
    assert len(run["nodes"]) == 2 * len(source.segments)
    for node in run["nodes"]:
        span = node.spans[0]
        assert schema.validate_node(node) == []
        assert node.schema_version == schema.version
        assert source.segment_text(span.segment)[span.start : span.end] == span.text


def test_a_type_of_the_shipped_pack_is_as_unknown_here_as_any_other_word(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    steps = STEPS.replace("Observation: subject", "Dataset: name")

    state = Pipeline.from_config(write_config(PACK, steps)).run([pdf])

    assert [node.type for node in state["nodes"]] == ["Instrument", "Instrument"]
    assert all("unknown type 'Dataset'" in violation for violation in state["violations"])


def test_the_invented_terms_are_found_by_name_by_curie_and_by_iri(run: dict) -> None:
    schema = run["schema"]
    observation = schema.find_type("Observation")

    assert schema.find_type("obs:Observation") is observation
    assert schema.find_type("https://example.org/ontology/observation#Observation") is observation
    assert schema.is_a("Observation", "obs:Observation")


def test_the_store_projects_the_run_back_under_the_invented_type_names(run: dict) -> None:
    store = run["store"]

    observations = store.by_type("Observation")

    assert len(observations) == len(store.nodes()) / 2
    assert len(store.assertions()) == len(run["nodes"])
    assert {assertion.agent.kind for assertion in store.assertions()} == {"run"}


def test_a_link_of_the_invented_predicate_validates_and_is_projected(run: dict) -> None:
    store, schema = run["store"], run["schema"]
    observation = store.by_type("Observation")[0]
    instrument = store.by_type("Instrument")[0]
    link = Link.of("recorded_with", observation.id, instrument.id,
                   observation.spans, schema.version)

    store.assert_(Assertion(id="link-1", agent=Agent(id="reviewer", kind="human"),
                            at="2024-05-02T00:00:00+00:00", target=link))

    assert schema.validate_link(link, observation.type, instrument.type) == []
    assert schema.validate_link(link, instrument.type, observation.type) != []
    assert store.links() == (link,)
    assert store.nodes() == run["nodes"]


def test_a_correction_lands_over_the_run_without_erasing_what_it_replaced(run: dict) -> None:
    store = run["store"]
    asserted = store.assertions()[0]
    corrected = Node(id=asserted.target.id, type=asserted.target.type, spans=asserted.target.spans,
                     schema_version=asserted.target.schema_version, fields={"subject": "the tide"})

    store.assert_(Assertion(id="fix-1", agent=Agent(id="reviewer", kind="human"),
                            at="2024-05-02T00:00:00+00:00", target=corrected,
                            supersedes=asserted.id))

    assert corrected in store.nodes()
    assert asserted.target not in store.nodes()
    assert store.assertions(corrected.id) == (asserted, store.assertions()[-1])
