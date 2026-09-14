"""Tests for the recording step: who a pass is attributed to, and what an id follows from.

The attribution is the whole configurable surface, so it is also the whole of what can
be got wrong in a file: the three kinds an agent may have are the three a configuration
may write, and the last test is the fourth spelling being refused before anything runs.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.model import FieldDef, Node, Schema, Segment, Source, Span, TypeDef
from atlas.pipeline import Pipeline
from atlas.steps import get
from atlas.steps.record import AssertOptions, record
from atlas.store.memory import MemoryStore

TEXT = "Точность распознавания составила 0,94.\n"
VERSION = "0" * 12
AT = "2025-01-01T00:00:00+00:00"
SOURCE = Source(id="doc-1", origin="corpus/doc-1.txt", segments=(Segment(number=1, text=TEXT),))
SCHEMA = Schema(
    version=VERSION,
    types=(TypeDef(name="Thing", fields=(FieldDef(name="name"),), label_field="name"),),
)
NODE = Node(id="n-1", type="Thing", spans=(Span.of(SOURCE, 1, 0, 9),),
            schema_version=VERSION, fields={"name": "точность"})
PACK = """
types:
  - name: Thing
    description: Anything the text names.
    fields: [name]
"""


def state() -> dict:
    return {"sources": (SOURCE,), "nodes": (NODE,), "schema": SCHEMA, "at": AT,
            "store": MemoryStore()}


def test_a_pass_nobody_signed_is_attributed_to_the_run_that_made_it() -> None:
    produced = record(state(), AssertOptions())

    [assertion] = produced["assertions"]
    assert produced["agent"] == f"run:{AT}"
    assert (assertion.agent.kind, assertion.agent.label) == ("run", "")
    assert produced["store"].get_schema(VERSION) == SCHEMA


def test_two_passes_by_the_same_reviewer_share_one_agent_id() -> None:
    """What the label is for: a person is known by their name, not by when they worked."""
    options = AssertOptions(agent="human", label="reviewer")

    first = record(state(), options)
    second = record(state() | {"at": "2025-06-01T00:00:00+00:00"}, options)

    assert first["agent"] == second["agent"] == "reviewer"
    assert first["assertions"][0].agent.kind == "human"
    # The time is still in the assertion, which is what orders the two.
    assert first["assertions"][0].id != second["assertions"][0].id


def test_replaying_an_unchanged_pass_writes_the_assertion_it_wrote_before() -> None:
    """The docstring's claim: an id follows from its content, so a replay is not a copy."""
    assert record(state(), AssertOptions())["assertions"][0].id == (
        record(state(), AssertOptions())["assertions"][0].id
    )


def test_a_kind_of_agent_the_metamodel_has_no_place_for_is_refused_when_the_file_is_read(
    write_config: Callable[[str, str], Path]
) -> None:
    """Before, `Agent` raised this from inside the step, after a whole pass had been paid for."""
    steps = "  - ingest_text\n  - {assert: {agent: robot}}\n"

    with pytest.raises(ValueError, match=re.escape("step 'assert': option 'agent':")) as refused:
        Pipeline.from_config(write_config(PACK, steps))

    assert "'human', 'model' or 'run'" in str(refused.value)
    assert "label: str = ''" in str(refused.value)


def test_the_step_is_called_through_the_registry_with_the_mapping_a_file_holds() -> None:
    produced = get("assert")(state(), {"agent": "model", "label": "extractor"})

    assert produced["assertions"][0].agent.kind == "model"
