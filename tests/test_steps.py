"""What the registry holds: every shipped step under its name, with its state keys declared.

The declaration is only worth making if it is checked, so the second test runs the
shipped steps out of order through a real configuration and reads the refusal. A step
whose `requires` or `produces` quietly stopped matching what its function does would
pass every test of its own module and fail here.

The rest is the other half of a declaration: what a step takes under its name. A
configuration that misspells an option, gives one the wrong type, or writes one under a
step that takes none is refused while the file is being read, with the file, the step and
the fields it knows in the message -- the alternative is a run whose file says one thing
and whose work does another.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.pipeline import Pipeline
from atlas.steps import Nothing, State, get, register

SHIPPED = (
    "ingest_pdf", "ingest_text", "ingest_markdown", "render_markdown", "extract_llm",
    "relocate", "validate", "assert", "index_nodes", "retrieve", "answer",
)
PACK = """
types:
  - name: Thing
    description: Anything the text names.
    fields: [name]
"""


@pytest.mark.parametrize("name", SHIPPED)
def test_every_shipped_step_is_registered_under_its_name_and_says_what_it_adds(name: str) -> None:
    step = get(name)

    assert step.name == name
    assert step.produces


@pytest.mark.parametrize("name", SHIPPED)
def test_the_options_documented_for_a_shipped_step_are_the_ones_it_takes(name: str) -> None:
    """The table in `docs/architecture.md` is what a user reads instead of the source.

    Each row is the library's own words for that step -- the half of a refusal that lists
    what it does take -- so an option added without its row is caught here and not by the
    reader, and the document cannot drift into claiming something that stopped being true.
    """
    doc = (Path(__file__).parent.parent / "docs" / "architecture.md").read_text(encoding="utf-8")

    with pytest.raises(ValueError) as refused:
        get(name).configure({"no_such_option": 1})

    assert str(refused.value).split("It takes ")[1] in doc.replace("\\|", "|")


def test_the_shipped_steps_in_the_wrong_order_are_refused_when_the_file_is_read(
    write_config: Callable[[str, str], Path]
) -> None:
    steps = "  - ingest_pdf\n  - validate\n  - relocate\n"

    with pytest.raises(ValueError, match="'validate' reads 'nodes', which 'relocate' produces"):
        Pipeline.from_config(write_config(PACK, steps))


def test_a_misspelt_option_is_refused_when_the_file_is_read_naming_the_step(
    write_config: Callable[[str, str], Path]
) -> None:
    """The misspelling this is written from: `treshold`, swallowed by `**options` before."""
    steps = "  - {retrieve: {limit: 8, treshold: 0.2}}\n"

    with pytest.raises(ValueError, match=re.escape(
        "step 'retrieve': unknown option 'treshold'. It takes limit: int = 8"
    )) as refused:
        Pipeline.from_config(write_config(PACK, steps))

    assert "pipeline.yaml" in str(refused.value)


def test_an_option_whose_value_is_of_the_wrong_type_is_refused_by_the_model_declaring_it(
    write_config: Callable[[str, str], Path]
) -> None:
    steps = '  - {retrieve: {limit: "eight"}}\n'

    with pytest.raises(ValueError, match=re.escape("step 'retrieve': option 'limit':")):
        Pipeline.from_config(write_config(PACK, steps))


def test_a_step_that_takes_no_options_refuses_the_one_it_is_given(
    write_config: Callable[[str, str], Path]
) -> None:
    steps = "  - {count_sources: {limit: 2}}\n"

    with pytest.raises(ValueError, match=re.escape(
        "step 'count_sources': unknown option 'limit'. It takes no options"
    )):
        Pipeline.from_config(write_config(PACK, steps))


def test_the_options_a_file_writes_reach_the_step_as_the_object_it_declared(
    write_config: Callable[[str, str], Path]
) -> None:
    """A valid file is read as it was before, with the values parsed into the model."""
    steps = "  - {retrieve: {limit: 2}}\n  - count_sources\n"

    pipeline = Pipeline.from_config(write_config(PACK, steps))

    assert [options for _step, options in pipeline.steps][0].limit == 2
    assert isinstance([options for _step, options in pipeline.steps][1], Nothing)


def test_a_step_that_declares_no_model_takes_nothing_rather_than_swallowing_anything(
    write_config: Callable[[str, str], Path]
) -> None:
    """The default is `Nothing`, so the path that used to swallow an option is gone.

    `count_inputs` names no model at all -- the shape of a step registered from outside
    this package by somebody who has not read the rule yet -- and is still refused.
    """
    steps = "  - {count_inputs: {limit: 2}}\n"

    with pytest.raises(ValueError, match=re.escape(
        "step 'count_inputs': unknown option 'limit'. It takes no options"
    )):
        Pipeline.from_config(write_config(PACK, steps))


def test_a_literal_option_is_named_in_the_message_without_the_typing_prefix() -> None:
    """The message is read by somebody editing YAML, where `typing.Literal` means nothing."""
    with pytest.raises(ValueError, match=re.escape(
        "split: Literal['blank-line', 'whole', 'window']"
    )):
        get("ingest_text").configure({"split": "sentences"})


def test_calling_a_step_by_name_refuses_the_option_reading_a_file_would() -> None:
    """The second door into a step is the registry, and it must not be the loose one."""
    with pytest.raises(ValueError, match=re.escape(
        "step 'count_sources': unknown option 'limit'. It takes no options"
    )):
        get("count_sources")({"sources": ()}, {"limit": 2})


@register("count_inputs", produces=("counted",))
def count_inputs(state: State) -> State:
    """A step registered the shortest way there is, naming no options model."""
    return {"counted": len(state["inputs"])}


@register("count_sources", requires=("sources",), produces=("counted",), options=Nothing)
def count_sources(state: State) -> State:
    """A step declaring that it takes nothing, so that a file writing an option is wrong."""
    return {"counted": len(state["sources"])}
