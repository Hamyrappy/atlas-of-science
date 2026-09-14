"""Tests for the pipeline: a file of step names runs over a PDF and leaves located nodes.

The extractor is the stub registered in `conftest`, which is the point of the registry:
the run is configured, not forked. What the test holds the pipeline to is the invariant
every step is arranged around -- a node's span re-slices to its own text.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.pipeline import Pipeline, summary
from atlas.store.memory import MemoryStore

PACK = """
types:
  - name: Thing
    description: Anything the text names.
    fields: [name]
"""

LINES = (
    ("Photosynthesis converts light into chemical energy.", "Chlorophyll absorbs blue light."),
    ("The rate saturates above a threshold irradiance.",),
)

STEPS = """\
  - ingest_pdf
  - {stub_extract: {types: {Thing: name}}}
  - relocate
  - validate
  - assert: {agent: run}
"""


@pytest.fixture
def pdf(build_pdf: Callable[..., bytes], tmp_path: Path) -> Path:
    path = tmp_path / "paper.pdf"
    path.write_bytes(build_pdf(LINES))
    return path


def test_a_configured_run_leaves_nodes_whose_spans_reslice_to_their_text(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    state = Pipeline.from_config(write_config(PACK, STEPS)).run([pdf])

    source = state["sources"][0]
    assert len(state["nodes"]) == len(source.segments) == 2
    assert state["violations"] == ()
    for node in state["nodes"]:
        span = node.spans[0]
        assert source.segment_text(span.segment)[span.start : span.end] == span.text
        assert node.type == "Thing"
        assert node.schema_version == state["schema"].version


def test_the_run_is_recorded_as_assertions_the_store_projects_back(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    store = MemoryStore()

    state = Pipeline.from_config(write_config(PACK, STEPS)).run([pdf], store=store)

    assert store.nodes() == state["nodes"]
    assert store.get_source(state["sources"][0].id) == state["sources"][0]
    assert {a.agent.kind for a in store.assertions()} == {"run"}
    assert {a.at for a in store.assertions()} == {state["at"]}


def test_a_second_pass_at_the_same_time_adds_no_second_copy(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    pipeline = Pipeline.from_config(write_config(PACK, STEPS))
    store = MemoryStore()

    first = pipeline.run([pdf], store=store, at="2024-05-01T00:00:00+00:00")
    again = pipeline.run([pdf], store=store, at="2024-05-01T00:00:00+00:00")

    assert [a.id for a in first["assertions"]] == [a.id for a in again["assertions"]]
    assert store.nodes() == first["nodes"]


def test_a_node_the_schema_refuses_is_dropped_and_reported(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    steps = STEPS.replace("Thing: name", "Nonesuch: name")

    state = Pipeline.from_config(write_config(PACK, steps)).run([pdf])

    assert state["nodes"] == ()
    assert len(state["violations"]) == 2
    assert "unknown type 'Nonesuch'" in state["violations"][0]


def test_an_option_from_the_file_reaches_the_step_it_is_written_under(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    steps = STEPS.replace("{stub_extract: {types: {Thing: name}}}", "stub_extract")

    state = Pipeline.from_config(write_config(PACK, steps)).run([pdf])

    assert [node.type for node in state["nodes"]] == ["Thing", "Thing"]


def test_an_unknown_step_name_is_refused_with_the_names_that_are_known(
    write_config: Callable[[str, str], Path]
) -> None:
    with pytest.raises(ValueError, match="unknown step 'summarise'"):
        Pipeline.from_config(write_config(PACK, "  - ingest_pdf\n  - summarise\n"))

    with pytest.raises(ValueError, match="registered: assert,"):
        Pipeline.from_config(write_config(PACK, "  - summarise\n"))


def test_a_step_written_with_two_names_in_one_entry_is_refused(
    write_config: Callable[[str, str], Path]
) -> None:
    with pytest.raises(ValueError, match="one name with its options"):
        Pipeline.from_config(write_config(PACK, "  - {relocate: null, validate: null}\n"))


def test_the_summary_counts_what_the_steps_left_and_names_nothing_else(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    state = Pipeline.from_config(write_config(PACK, STEPS)).run([pdf])

    counts = dict(part.split(" ") for part in summary(state).split("\t"))

    assert counts == {
        "inputs": "1", "sources": "1", "statements": "2", "malformed": "0",
        "nodes": "2", "unplaced": "0", "needs_review": "0", "violations": "0",
        "assertions": "2",
    }


def test_the_configuration_the_repository_ships_resolves_against_the_pack_it_names() -> None:
    pipeline = Pipeline.from_config(Path(__file__).parents[1] / "pipeline.yaml")

    assert len(pipeline.steps) == 6
    assert len(pipeline.schema.types) == 6
