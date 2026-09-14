"""The registry: a step is a named function, and a name is what a configuration holds.

A step takes the state of a run plus the options it was configured with, and returns
the keys it adds to that state. The dict below is the whole mechanism, so replacing a
step is writing a function and registering it under another name -- no subclass to
derive, no pipeline to fork -- and a configuration file is free to name either one.

What a step reads out of the state and what it puts back used to be a convention held
together by tests; `requires` and `produces` write it down, so a configuration whose
steps are in the wrong order is refused when the file is read rather than raising a
`KeyError` from inside a step. They are names of state keys and nothing more: no types,
no ordering solver, no graph.

The imports at the bottom populate the registry: a name cannot be resolved out of a
file before the module that defines it has been imported. A configuration may name a
step from outside this package by listing its module under `imports:`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

State = dict[str, Any]
Function = Callable[..., State]


@dataclass(frozen=True)
class Step:
    """A registered function under the name a configuration calls it by, and its state keys."""

    name: str
    function: Function
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def __call__(self, state: State, **options: Any) -> State:
        return self.function(state, **options)


_STEPS: dict[str, Step] = {}


def register(
    name: str, requires: Iterable[str] = (), produces: Iterable[str] = ()
) -> Callable[[Function], Function]:
    """Register a function under a name, declaring the state keys it reads and adds."""

    def bind(function: Function) -> Function:
        _STEPS[name] = Step(name, function, tuple(requires), tuple(produces))
        return function

    return bind


def get(name: str) -> Step:
    """The step registered under a name, or a ValueError naming the ones that are."""
    if name not in _STEPS:
        raise ValueError(
            f"unknown step {name!r}; registered: {', '.join(sorted(_STEPS))}. "
            "A step from another package is registered when its module is imported: "
            "name it under `imports:` in the configuration."
        )
    return _STEPS[name]


from atlas.steps import (  # noqa: E402, F401
    answer,
    extract_llm,
    index_nodes,
    ingest_pdf,
    ingest_text,
    markdown,
    record,
    relocate,
    retrieve,
    validate,
)
