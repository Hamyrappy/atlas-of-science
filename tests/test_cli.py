"""CLI tests: argument handling, exit codes, and the files each subcommand leaves behind.

The library runs for real, on a PDF built in a fixture and under a pack written by the
test; only the extractor is the stub, since it is the one step that would need a model.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.cli import main
from atlas.pipeline import Pipeline
from atlas.scaffold import FILES, scaffold
from atlas.store.jsonl import JsonlStore

MODEL_VARIABLES = ("ATLAS_BASE_URL", "ATLAS_MODEL", "ATLAS_API_KEY")
LINES = (
    ("Iron oxidises in damp air.", "The rate rises with temperature."),
    ("A coating of zinc delays the onset.",),
)
CONFIGURED_STORE = "store: {jsonl: {dir: written}}\n"
PACK = """
types:
  - name: Thing
    description: Anything the text names.
    fields: [name]
"""
STEPS = """\
  - ingest_pdf
  - {stub_extract: {types: {Thing: name}}}
  - relocate
  - validate
  - assert: {agent: run}
"""


@pytest.fixture
def pdf(tmp_path: Path, build_pdf: Callable[..., bytes]) -> Path:
    path = tmp_path / "sample.pdf"
    path.write_bytes(build_pdf(LINES))
    return path


@pytest.fixture
def model_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in MODEL_VARIABLES:
        monkeypatch.setenv(variable, "unused")


def test_no_subcommand_prints_usage_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])

    assert code != 0
    assert "usage: atlas" in capsys.readouterr().err


@pytest.mark.usefixtures("model_environment")
def test_run_writes_the_nodes_of_the_run_into_the_store_it_names(
    pdf: Path, tmp_path: Path,
    write_config: Callable[[str, str], Path], capsys: pytest.CaptureFixture[str],
) -> None:
    store = tmp_path / "store"

    code = main(["run", str(write_config(PACK, STEPS)), str(pdf), "--store", str(store)])
    printed = capsys.readouterr().out.splitlines()

    reopened = JsonlStore(store)
    assert code == 0
    assert [node.type for node in reopened.nodes()] == ["Thing", "Thing"]
    assert len(printed) == 1
    fields = printed[0].split("\t")
    assert fields[-3:-1] == ["assertions 2", f"store {store}"]
    # The last field is what the store recorded the pass cost, which only it knows.
    assert fields[-1] == f"{reopened.runs()[-1].seconds}s"


@pytest.mark.usefixtures("model_environment")
def test_run_reads_every_input_it_is_given(
    pdf: Path, tmp_path: Path,
    write_config: Callable[[str, str], Path], capsys: pytest.CaptureFixture[str],
    build_pdf: Callable[..., bytes],
) -> None:
    second = tmp_path / "second.pdf"
    second.write_bytes(build_pdf((("Copper corrodes more slowly.",),)))

    code = main([
        "run", str(write_config(PACK, STEPS)), str(pdf), str(second),
        "--store", str(tmp_path / "store"),
    ])

    assert code == 0
    assert "sources 2" in capsys.readouterr().out


def test_run_without_the_model_environment_fails_on_one_line_and_writes_nothing(
    pdf: Path, tmp_path: Path, write_config: Callable[[str, str], Path],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    for variable in MODEL_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    store = tmp_path / "store"

    code = main(["run", str(write_config(PACK, STEPS)), str(pdf), "--store", str(store)])
    captured = capsys.readouterr()

    assert code != 0
    assert len(captured.err.splitlines()) == 1
    assert "ATLAS_BASE_URL" in captured.err
    assert not store.exists()


@pytest.mark.usefixtures("model_environment")
@pytest.mark.parametrize(
    ("steps", "expected"),
    [(STEPS, "missing.yaml"), ("  - summarise\n", "unknown step")],
    ids=["missing config", "unknown step"],
)
def test_run_reports_a_configuration_it_cannot_use_on_one_line(
    steps: str, expected: str, pdf: Path, tmp_path: Path,
    write_config: Callable[[str, str], Path], capsys: pytest.CaptureFixture[str],
) -> None:
    config = write_config(PACK, steps)
    named = config if expected == "unknown step" else tmp_path / "missing.yaml"

    code = main(["run", str(named), str(pdf), "--store", str(tmp_path / "store")])
    captured = capsys.readouterr()

    assert code != 0
    assert len(captured.err.splitlines()) == 1
    assert expected in captured.err


def test_init_writes_a_project_and_prints_every_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "corpus"

    code = main(["init", str(project)])
    printed = capsys.readouterr().out.splitlines()

    assert code == 0
    assert printed == [str(project / name) for name in FILES]
    assert all((project / name).exists() for name in FILES)


def test_init_refuses_to_overwrite_a_project_already_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["init", str(tmp_path)])
    (tmp_path / "pack.yaml").write_text("types: []\n", encoding="utf-8")

    code = main(["init", str(tmp_path)])
    captured = capsys.readouterr()

    assert code != 0
    assert len(captured.err.splitlines()) == 1
    assert (tmp_path / "pack.yaml").read_text(encoding="utf-8") == "types: []\n"


def test_the_project_init_writes_is_a_configuration_that_loads(tmp_path: Path) -> None:
    main(["init", str(tmp_path)])

    pipeline = Pipeline.from_config(tmp_path / "pipeline.yaml")

    assert pipeline.schema.type_names() == {"Thing"}
    assert len(pipeline.steps) == 6


@pytest.mark.usefixtures("model_environment")
def test_run_writes_into_the_store_the_configuration_names_when_no_directory_is_given(
    pdf: Path, tmp_path: Path, write_config: Callable[[str, str], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = write_config(PACK, STEPS)
    config.write_text(CONFIGURED_STORE + config.read_text(encoding="utf-8"), encoding="utf-8")

    code = main(["run", str(config), str(pdf)])

    assert code == 0
    assert len(JsonlStore(tmp_path / "written").nodes()) == 2
    assert f"store {tmp_path / 'written'}" in capsys.readouterr().out


@pytest.mark.usefixtures("model_environment")
def test_a_named_directory_overrides_the_store_the_configuration_names(
    pdf: Path, tmp_path: Path, write_config: Callable[[str, str], Path],
) -> None:
    config = write_config(PACK, STEPS)
    config.write_text(CONFIGURED_STORE + config.read_text(encoding="utf-8"), encoding="utf-8")

    code = main(["run", str(config), str(pdf), "--store", str(tmp_path / "elsewhere")])

    assert code == 0
    assert len(JsonlStore(tmp_path / "elsewhere").nodes()) == 2
    assert JsonlStore(tmp_path / "written").nodes() == ()


def test_init_writes_the_templates_it_is_handed_instead_of_the_default_ones(
    tmp_path: Path
) -> None:
    templates = {"corpus.yaml": "name: papers\n", "inputs/README.md": "Put the papers here.\n"}

    written = scaffold(tmp_path / "papers", templates)

    assert written == (tmp_path / "papers/corpus.yaml", tmp_path / "papers/inputs/README.md")
    assert written[1].read_text(encoding="utf-8") == "Put the papers here.\n"
    assert not (tmp_path / "papers/pack.yaml").exists()
