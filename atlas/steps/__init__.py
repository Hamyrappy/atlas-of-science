"""The registry: a step is a named function, and a name is what a configuration holds.

A step takes the state of a run plus the options it was configured with, and returns
the keys it adds to that state. The dict below is the whole mechanism, so replacing a
step is writing a function and registering it under another name -- no subclass to
derive, no pipeline to fork -- and a configuration file is free to name either one.

What a step reads out of the state and what it puts back used to be a convention held
together by tests; `requires` and `produces` write it down, so a configuration whose
steps are in the wrong order is refused when the file is read rather than raising a
`KeyError` from inside a step. They are names of state keys and nothing more: no types,
no ordering solver, no graph -- `docs/architecture.md` says what typing them would have
cost and what it would have caught.

What a configuration may write under a step's name is declared the same way, and is
checked: `options` names a `Frozen` subclass whose fields are the options the step
takes. A misspelt key, a missing one and a value of the wrong type are all refused when
the file is read, naming the step and the fields it knows, rather than being swallowed
so that the file says one thing and the run does another. A step that takes nothing says
so with `options=Nothing` and is then refused every option written under its name. The
model is the declaration and the parser at once: a step that declares one is called with
it, so a default is written where its type is and nowhere else.

The imports at the bottom populate the registry: a name cannot be resolved out of a
file before the module that defines it has been imported. A configuration may name a
step from outside this package by listing its module under `imports:`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from atlas.model import Frozen

State = dict[str, Any]
Function = Callable[..., State]


class Nothing(Frozen):
    """The options of a step that takes none: no fields, so any option written is refused."""


@dataclass(frozen=True)
class Step:
    """A registered function under the name a configuration calls it by, its keys, its options."""

    name: str
    function: Function
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    options: type[Frozen] = Nothing

    def configure(self, given: Any = None) -> Frozen:
        """What a configuration wrote under this step's name, as the object the step declared.

        Raises a ValueError naming the step, what is wrong with the options and the ones
        it knows; the file that holds them is added by whoever read it.
        """
        if given is not None and not isinstance(given, Mapping):
            raise ValueError(f"step {self.name!r}: options are a mapping of names to values, "
                             f"not {given!r}")
        given = dict(given or {})
        try:
            return self.options(**given)
        except ValidationError as invalid:
            raise ValueError(f"step {self.name!r}: "
                             + "; ".join(_why(error) for error in invalid.errors())
                             + f". It takes {_takes(self.options)}") from invalid

    def __call__(self, state: State, options: Frozen | Mapping[str, Any] | None = None) -> State:
        """Run the step over a state, with the options object it declared or their defaults.

        A mapping is validated here if it has not been already, so calling a step by name
        refuses exactly what reading a file refuses -- including an option written under a
        step that takes none, which is the whole point and must not be dropped here. A step
        whose model has no fields is then called with the state alone: nothing to hand it.
        """
        if not isinstance(options, Frozen):
            options = self.configure(options)
        if not self.options.model_fields:
            return self.function(state)
        return self.function(state, options)


_STEPS: dict[str, Step] = {}


def register(
    name: str,
    requires: Iterable[str] = (),
    produces: Iterable[str] = (),
    options: type[Frozen] = Nothing,
) -> Callable[[Function], Function]:
    """Register a function under a name, declaring the state keys it uses and what it takes.

    A step that does not name an options model takes none, and any option a configuration
    writes under its name is refused: there is no path left that swallows one.
    """

    def bind(function: Function) -> Function:
        _STEPS[name] = Step(name, function, tuple(requires), tuple(produces), options)
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


def _takes(options: type[Frozen]) -> str:
    """The options a step knows, written as the fields declaring them are: name, type, default."""
    if not options.model_fields:
        return "no options"
    return ", ".join(
        f"{name}: {_named(field.annotation)}"
        + ("" if field.is_required() else f" = {field.default!r}")
        for name, field in options.model_fields.items()
    )


def _why(error: Mapping[str, Any]) -> str:
    """One pydantic error as the sentence somebody editing a configuration file needs."""
    field = ".".join(str(part) for part in error["loc"])
    if error["type"] == "extra_forbidden":
        return f"unknown option {field!r}"
    if error["type"] == "missing":
        return f"option {field!r} is required"
    return f"option {field!r}: {error['msg']}, and was given {error['input']!r}"


def _named(annotation: Any) -> str:
    """What to call a type in a message: `int`, `str | None`, `Literal['whole', 'window']`.

    The `typing.` prefix `str()` puts on a `Literal` is dropped: the reader of the message
    is editing a configuration file, where no Python name is in scope anyway.
    """
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace("typing.", "")


from atlas.steps import (  # noqa: E402, F401
    align,
    answer,
    check_answer,
    communities,
    compare,
    critique,
    define_llm,
    entail,
    extract_llm,
    federate,
    formal_check,
    graph_answer,
    graph_expand,
    graph_sql,
    index_nodes,
    induce,
    ingest_pdf,
    ingest_text,
    lineage,
    markdown,
    reconcile,
    record,
    relate,
    relate_llm,
    relocate,
    repair,
    retrieve,
    route,
    salience,
    topics,
    units,
    validate,
)
