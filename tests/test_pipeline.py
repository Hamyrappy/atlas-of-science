"""Tests for the pipeline: a file of step names runs over a PDF and leaves located nodes.

The extractor is the stub registered in `conftest`, which is the point of the registry:
the run is configured, not forked. What the test holds the pipeline to is the invariant
every step is arranged around -- a node's span re-slices to its own text, and around
that: that a run can be watched, entered part-way, and leaves a record of what it cost.

Two steps at the bottom declare state keys the shipped ones do not, so the check the
pipeline makes when it reads a file has something to be wrong about.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from atlas.pipeline import Pipeline, summary
from atlas.steps import State, register
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

    with pytest.raises(ValueError, match="registered: .*ingest_pdf"):
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


def test_a_watcher_is_told_the_configured_name_of_every_step_in_order(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    seen: list[tuple[str, int, tuple[str, ...]]] = []

    state = Pipeline.from_config(write_config(PACK, STEPS)).run(
        [pdf], on_step=lambda name, index, produced, _state: seen.append(
            (name, index, tuple(produced))
        )
    )

    assert [name for name, _index, _produced in seen] == [
        "ingest_pdf", "stub_extract", "relocate", "validate", "assert"
    ]
    assert [index for _name, index, _produced in seen] == [0, 1, 2, 3, 4]
    assert seen[-1][2] == ("store", "assertions", "agent")
    assert state["nodes"] == state["nodes"]


def test_the_configured_names_stay_on_the_pipeline(
    write_config: Callable[[str, str], Path]
) -> None:
    pipeline = Pipeline.from_config(write_config(PACK, STEPS))

    assert [step.name for step, _options in pipeline.steps] == [
        "ingest_pdf", "stub_extract", "relocate", "validate", "assert"
    ]
    assert [options for _step, options in pipeline.steps][1] == {"types": {"Thing": "name"}}


def test_the_initial_state_is_public_and_the_caller_overrides_any_of_it(
    write_config: Callable[[str, str], Path]
) -> None:
    pipeline = Pipeline.from_config(write_config(PACK, STEPS))

    state = pipeline.initial(["paper.pdf"], at="2024-05-01T00:00:00+00:00", question="why?")

    assert state["inputs"] == ("paper.pdf",)
    assert state["schema"] is pipeline.schema
    assert state["at"] == "2024-05-01T00:00:00+00:00"
    assert state["question"] == "why?"


def test_a_state_the_caller_built_is_run_over_the_same_chain(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    pipeline = Pipeline.from_config(write_config(PACK, STEPS))
    seen: list[str] = []

    state = pipeline.run_state(
        {"inputs": (pdf,), "schema": pipeline.schema, "at": "2024-05-01T00:00:00+00:00"},
        on_step=lambda name, _index, _produced, _state: seen.append(name),
    )

    assert len(state["nodes"]) == 2
    assert seen[0] == "ingest_pdf"


def test_a_run_over_a_store_leaves_a_record_of_what_it_counted(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    store = MemoryStore()
    pipeline = Pipeline.from_config(write_config(PACK, STEPS))

    state = pipeline.run([pdf], store=store, at="2024-05-01T00:00:00+00:00")

    [run] = store.runs()
    assert run.at == state["at"]
    assert run.pipeline == "pipeline.yaml"
    assert run.schema_version == pipeline.schema.version
    assert run.counts["nodes"] == 2 and run.counts["unplaced"] == 0
    assert run.seconds >= 0.0
    # The step that wrote the assertions is the only thing that knows who they are attributed to.
    assert run.agent == "run:2024-05-01T00:00:00+00:00"


def test_a_second_identical_pass_records_the_run_it_recorded_before(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    store = MemoryStore()
    pipeline = Pipeline.from_config(write_config(PACK, STEPS))

    first = pipeline.run([pdf], store=store, at="2024-05-01T00:00:00+00:00")
    pipeline.run([pdf], store=store, at="2024-05-01T00:00:00+00:00")

    # Two passes, two rows -- nothing is deduplicated -- under the one id their content implies.
    assert len(store.runs()) == 2
    assert len({run.id for run in store.runs()}) == 1
    assert store.runs()[0].counts["assertions"] == len(first["assertions"])


def test_a_run_that_never_reaches_a_store_records_nothing_and_still_returns_its_state(
    pdf: Path, write_config: Callable[[str, str], Path]
) -> None:
    state = Pipeline.from_config(write_config(PACK, "  - ingest_pdf\n")).run([pdf])

    assert "store" not in state
    assert len(state["sources"]) == 1


def test_the_store_a_configuration_names_is_opened_and_handed_to_the_steps(
    pdf: Path, tmp_path: Path
) -> None:
    config = _config(tmp_path, store={"jsonl": {"dir": "store"}})

    state = Pipeline.from_config(config).run([pdf])

    assert state["store"].location == tmp_path / "store"
    assert len(state["store"].nodes()) == 2
    assert len(state["store"].runs()) == 1


def test_keys_the_pipeline_does_not_reserve_are_kept_for_the_caller(
    tmp_path: Path
) -> None:
    config = _config(tmp_path, name="One pass", note="what it is for")

    pipeline = Pipeline.from_config(config)

    assert pipeline.meta == {"name": "One pass", "note": "what it is for"}


def test_a_step_that_reads_a_key_a_later_step_produces_is_refused_by_name(
    tmp_path: Path
) -> None:
    config = _config(tmp_path, steps=["cite", "rank"])

    with pytest.raises(ValueError, match="pipeline.yaml: step 'cite' reads 'ranked'"):
        Pipeline.from_config(config)


def test_a_key_no_step_in_the_file_produces_is_the_callers_to_supply(tmp_path: Path) -> None:
    config = _config(tmp_path, steps=["rank", "cite"])

    pipeline = Pipeline.from_config(config)

    assert [step.name for step, _options in pipeline.steps] == ["rank", "cite"]


def test_a_configuration_may_name_a_step_from_a_package_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "outside_steps.py").write_text(
        "from atlas.steps import register\n\n\n"
        '@register("count_inputs", produces=("counted",))\n'
        "def count_inputs(state):\n"
        '    return {"counted": len(state["inputs"])}\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    config = _config(tmp_path, imports=["outside_steps"], steps=["count_inputs"])

    state = Pipeline.from_config(config).run(["a.pdf", "b.pdf"])

    assert state["counted"] == 2


def test_a_value_that_knows_its_own_size_is_counted_without_a_step_saying_so(
    tmp_path: Path
) -> None:
    pipeline = Pipeline.from_config(_config(tmp_path, steps=["rank"]))

    state = pipeline.run_state({"question": "what is this"})

    assert summary(state) == "ranked 3"


@register("rank", requires=("question",), produces=("ranked",))
def rank(state: State) -> State:
    """A step whose one product is a value that knows its own length and nothing else."""
    return {"ranked": Ranking(len(state["question"].split()))}


@register("cite", requires=("ranked",), produces=("cited",))
def cite(state: State) -> State:
    return {"cited": len(state["ranked"])}


class Ranking:
    """Something a step returns that is neither an int nor a tuple, and has a size."""

    def __init__(self, size: int) -> None:
        self.size = size

    def __len__(self) -> int:
        return self.size


def _config(directory: Path, **keys: object) -> Path:
    """A configuration of one's own: the pack of this module, plus whatever is named here."""
    (directory / "pack.yaml").write_text(PACK, encoding="utf-8")
    steps = ["ingest_pdf", {"stub_extract": None}, "relocate", "validate",
             {"assert": {"agent": "run"}}]
    config = {"schema": "pack.yaml", "steps": steps}
    path = directory / "pipeline.yaml"
    path.write_text(yaml.safe_dump(config | dict(keys)), encoding="utf-8")
    return path
