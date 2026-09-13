"""The registry: a step is a named function, and a name is what a configuration holds.

A step takes the state of a run plus the options it was configured with, and returns
the keys it adds to that state. The dict below is the whole mechanism, so replacing a
step is writing a function and registering it under another name -- no subclass to
derive, no pipeline to fork -- and a configuration file is free to name either one.

The imports at the bottom populate the registry: a name cannot be resolved out of a
file before the module that defines it has been imported.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

State = dict[str, Any]
Step = Callable[..., State]

_STEPS: dict[str, Step] = {}


def register(name: str) -> Callable[[Step], Step]:
    """Register a function under the name a configuration may call it by."""

    def bind(step: Step) -> Step:
        _STEPS[name] = step
        return step

    return bind


def get(name: str) -> Step:
    """The step registered under a name, or a ValueError naming the ones that are."""
    if name not in _STEPS:
        raise ValueError(f"unknown step {name!r}; registered: {', '.join(sorted(_STEPS))}")
    return _STEPS[name]


from atlas.steps import (  # noqa: E402, F401
    extract_llm,
    ingest_pdf,
    markdown,
    record,
    relocate,
    validate,
)
