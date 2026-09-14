"""What the registry holds: every shipped step under its name, with its state keys declared.

The declaration is only worth making if it is checked, so the second test runs the
shipped steps out of order through a real configuration and reads the refusal. A step
whose `requires` or `produces` quietly stopped matching what its function does would
pass every test of its own module and fail here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.pipeline import Pipeline
from atlas.steps import get

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


def test_the_shipped_steps_in_the_wrong_order_are_refused_when_the_file_is_read(
    write_config: Callable[[str, str], Path]
) -> None:
    steps = "  - ingest_pdf\n  - validate\n  - relocate\n"

    with pytest.raises(ValueError, match="'validate' reads 'nodes', which 'relocate' produces"):
        Pipeline.from_config(write_config(PACK, steps))
