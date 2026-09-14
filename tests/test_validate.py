"""Tests for validation: what the pack refuses is dropped and counted, never repaired.

The step has no settings of its own, and the second test is that claim made checkable:
the pack decides, so a configuration writing anything under this name is wrong about
the library and is told so while the file is open.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.model import FieldDef, Node, Schema, Segment, Source, Span, TypeDef
from atlas.pipeline import Pipeline
from atlas.steps import Nothing, get
from atlas.steps.validate import validate

TEXT = "Точность распознавания составила 0,94.\n"
VERSION = "0" * 12
SOURCE = Source(id="doc-1", origin="corpus/doc-1.txt", segments=(Segment(number=1, text=TEXT),))
SCHEMA = Schema(
    version=VERSION,
    types=(TypeDef(name="Thing", fields=(FieldDef(name="name"),), label_field="name"),),
)
PACK = """
types:
  - name: Thing
    description: Anything the text names.
    fields: [name]
"""


def node(node_id: str, type_name: str, **fields: str) -> Node:
    return Node(
        id=node_id,
        type=type_name,
        spans=(Span.of(SOURCE, 1, 0, 9),),
        schema_version=VERSION,
        fields=fields,
    )


def test_a_node_of_a_type_the_pack_does_not_declare_costs_one_node_and_not_the_pass() -> None:
    kept = node("n-1", "Thing", name="точность")
    state = validate({"nodes": (kept, node("n-2", "Other", name="нечто")), "schema": SCHEMA})

    assert state["nodes"] == (kept,)
    assert len(state["violations"]) == 1
    assert "unknown type 'Other'" in state["violations"][0]


def test_the_step_takes_nothing_and_a_file_writing_an_option_is_refused_naming_it(
    write_config: Callable[[str, str], Path]
) -> None:
    """A `strict` that was never read: swallowed before, refused now with the step named."""
    steps = "  - relocate\n  - {validate: {strict: true}}\n"

    with pytest.raises(ValueError, match=re.escape(
        "step 'validate': unknown option 'strict'. It takes no options"
    )) as refused:
        Pipeline.from_config(write_config(PACK, steps))

    assert "pipeline.yaml" in str(refused.value)
    assert get("validate").options is Nothing
