"""A run is a list of named steps over one dict of state, and a file says which ones.

This is deliberately not a framework: it resolves the names in a configuration against
the step registry, holds the options each step was configured with, and calls them in
order, passing one dict along. Replacing a step is naming a different one in the file,
and configuring a step is a key under its name -- neither is a reason to edit this
module, and there is nothing here to subclass.

The schema is loaded once, from the packs the configuration names, and every step sees
it in the state: the pipeline is the seam where an ontology is plugged in.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from atlas.model import Schema
from atlas.ontology import load
from atlas.steps import State, Step, get


class Pipeline:
    """The steps one configuration names, and the schema they are all run under."""

    def __init__(self, schema: Schema, steps: tuple[tuple[Step, dict], ...]) -> None:
        self.schema = schema
        self.steps = steps

    @classmethod
    def from_config(cls, path: Path | str) -> Pipeline:
        """Read a configuration: the packs to load, and the steps to run in order.

        Pack paths are resolved against the directory of the configuration, so a
        configuration and the vocabulary it names travel together.
        """
        path = Path(path)
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        packs = config.get("schema") or ()
        packs = [packs] if isinstance(packs, str) else packs
        return cls(
            load(*(path.parent / pack for pack in packs)),
            tuple(_step(entry) for entry in config.get("steps") or ()),
        )

    def run(self, inputs: Iterable[Path | str], **context: Any) -> State:
        """Call every step in order over one state, and return what that state holds at the end.

        A run is stamped once with the time it happened, which every assertion it
        writes then carries; a backfill overrides it, as it does any other key.
        """
        state: State = {
            "inputs": tuple(inputs),
            "schema": self.schema,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            **context,
        }
        for step, options in self.steps:
            state |= step(state, **options)
        return state


def summary(state: State) -> str:
    """Every count a run left in its state, as one line: a tuple by its length, an int as it is.

    Which counts exist is the configuration's business, so nothing here names a key.
    """
    return "\t".join(
        f"{key} {value if isinstance(value, int) else len(value)}"
        for key, value in state.items()
        if isinstance(value, int | tuple)
    )


def _step(entry: str | dict) -> tuple[Step, dict]:
    """One entry of the steps list: a bare name, or a name with its options under it."""
    if isinstance(entry, str):
        return get(entry), {}
    if len(entry) != 1:
        raise ValueError(f"a step is one name with its options, not {sorted(entry)}")
    [(name, options)] = entry.items()
    return get(name), options or {}
