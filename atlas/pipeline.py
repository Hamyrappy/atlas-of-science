"""A run is a list of named steps over one dict of state, and a file says which ones.

This is deliberately not a framework: it resolves the names in a configuration against
the step registry, holds the options each step was configured with, and calls them in
order, passing one dict along. Replacing a step is naming a different one in the file,
and configuring a step is a key under its name -- neither is a reason to edit this
module, and there is nothing here to subclass.

The schema is loaded once, from the ontologies the configuration names, and every step
sees it in the state: the pipeline is the seam where an ontology is plugged in. `schema`
is a name, a list of names, or a mapping that also says which OWL 2 profile the ontology
must stay within and which SHACL shapes the records are held to:

    schema:
      ontologies: [science_core_rl, scierc_rl]
      profile: RL
      shapes: [science_core]

An ontology outside the profile it names is refused when the file is read, with the
axioms that leave it -- the configuration is a contract with the engine it runs.

A run can be watched and entered part-way: `on_step` is called with the name each step
was configured under, `initial` is public, and `run_state` runs the chain over a state
the caller built, which is the shape a request has and a batch run has not.

A configuration reserves five keys -- `schema`, `store`, `imports`, `steps`, `ask` --
and every other key is the caller's, kept in `Pipeline.meta` and read by nothing here.

A file may hold more than one chain. `steps` is the one a run takes by default and
`ask` is the one that answers a question over what that run wrote, because those are
two different chains over one vocabulary and one store, and splitting them into two
files would put the pack, the store and the options in two places to be kept in step.
`chain` names which of them to read; everything else about reading a configuration --
the imports, the ordering check, the options -- is the same whichever was named.

The options written under a step's name are validated when the file is read, against the
model that step declared it takes, so a misspelt or wrongly typed one is refused with the
file and the step in the message rather than being swallowed.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import time
from collections.abc import Callable, Iterable, Mapping, Sized
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from atlas.model import Frozen, Run, Schema
from atlas.ontology import load
from atlas.steps import State, Step, get
from atlas.store import Store, open_store

RESERVED = ("schema", "store", "imports", "steps", "ask")
CHAIN = "steps"
ASK = "ask"
SEEDED = ("inputs", "schema", "at", "store")
OnStep = Callable[[str, int, State, State], None]


class Pipeline:
    """The steps one configuration names, and the schema they are all run under."""

    def __init__(self, schema: Schema, steps: tuple[tuple[Step, Frozen], ...], *,
                 store: Store | None = None, meta: Mapping[str, Any] | None = None,
                 name: str = "") -> None:
        self.schema = schema
        self.steps = steps
        self.store = store
        self.meta: Mapping[str, Any] = dict(meta or {})
        self.name = name

    @classmethod
    def from_config(cls, path: Path | str, chain: str = CHAIN) -> Pipeline:
        """Read a configuration: packs, store, imports, and the steps of one chain, in order.

        Packs and the store are resolved against the directory of the configuration, so
        it travels with what it names; `imports` is read before the step names are, which
        is how a file names a step from a package of its own. The options under every
        step name are validated here, against what that step declared, so a file that
        misspells one is refused before a run starts rather than running without it.

        `chain` is which list of steps to read -- `steps` to build, `ask` to answer over
        what was built. A file that does not hold the named chain is refused by name,
        because a run that silently does nothing is the worst of the three outcomes.
        """
        path = Path(path)
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if chain != CHAIN and not config.get(chain):
            held = ", ".join(key for key in RESERVED if config.get(key)) or "nothing"
            raise ValueError(f"{path}: no {chain!r} chain; it holds {held}")
        for module in _listed(config.get("imports")):
            importlib.import_module(module)
        steps = tuple(_step(path, entry) for entry in config.get(chain) or ())
        _check_order(path, steps)
        return cls(
            _schema(config.get("schema"), path),
            steps,
            store=open_store(config["store"], path.parent) if config.get("store") else None,
            meta={key: value for key, value in config.items() if key not in RESERVED},
            name=path.name if chain == CHAIN else f"{path.name}:{chain}",
        )

    def initial(self, inputs: Iterable[Path | str] = (), **context: Any) -> State:
        """The state a run starts from: inputs, schema, the moment it happened, the store
        the configuration named. Anything the caller passes wins, a backfilled `at` included.
        """
        state: State = {"inputs": tuple(inputs), "schema": self.schema,
                        "at": datetime.now(UTC).isoformat(timespec="seconds")}
        if self.store is not None:
            state["store"] = self.store
        return state | context

    def run(self, inputs: Iterable[Path | str], on_step: OnStep | None = None,
            **context: Any) -> State:
        """Run every step over a fresh state, record what the pass cost, return the state."""
        started = time.monotonic()
        state = self.run_state(self.initial(inputs, **context), on_step=on_step)
        self._record(state, time.monotonic() - started)
        return state

    def run_state(self, state: State, on_step: OnStep | None = None) -> State:
        """Run every step over a state the caller built, and return what it holds at the end.

        A question answered over a store is a run of the same chain with nothing to ingest.
        """
        for index, (step, options) in enumerate(self.steps):
            produced = step(state, options)
            state = state | produced
            if on_step is not None:
                on_step(step.name, index, produced, state)
        return state

    def _record(self, state: State, seconds: float) -> None:
        """Hand the store a record of the pass, when the run had a store at all."""
        store: Store | None = state.get("store")
        if store is None:
            return
        counted = counts(state)
        store.add_run(Run(
            id=_run_id(self.name, state["at"], self.schema.version, counted),
            at=state["at"],
            pipeline=self.name,
            schema_version=self.schema.version,
            agent=str(state.get("agent") or ""),
            counts=counted,
            seconds=round(seconds, 3),
        ))


def counts(state: State) -> dict[str, int]:
    """What a run left that can be counted: an int as it is, anything sized by its length.

    Which counts exist is the configuration's business, so nothing here names a key, and a
    step need not return an integer to be visible. Text is skipped: its length counts nothing.
    """
    counted = {}
    for key, value in state.items():
        if isinstance(value, bool | str | bytes):
            continue
        if isinstance(value, int):
            counted[key] = value
        elif isinstance(value, Sized):
            counted[key] = len(value)
    return counted


def summary(state: State) -> str:
    """Every count a run left in its state, as one line."""
    return "\t".join(f"{key} {value}" for key, value in counts(state).items())


def _step(path: Path, entry: str | dict) -> tuple[Step, Frozen]:
    """One entry of the steps list: a bare name, or a name with its options under it.

    The options are read into the model the step declared, so the file is what refuses a
    misspelt or wrongly typed one, and the message says which file said it.
    """
    if isinstance(entry, str):
        name, options = entry, None
    elif len(entry) != 1:
        raise ValueError(f"a step is one name with its options, not {sorted(entry)}")
    else:
        [(name, options)] = entry.items()
    step = get(name)
    try:
        return step, step.configure(options)
    except ValueError as invalid:
        raise ValueError(f"{path}: {invalid}") from invalid


def _check_order(path: Path, steps: tuple[tuple[Step, Frozen], ...]) -> None:
    """Refuse a chain in which a step reads a key only a later step produces.

    A key no step in the file produces belongs to the caller -- a client, a question -- and
    passes; one produced further down is an ordering mistake, named here with the file
    rather than left to become a `KeyError` inside a step.
    """
    available = set(SEEDED)
    for index, (step, _options) in enumerate(steps):
        for key in (name for name in step.requires if name not in available):
            producer = next((s.name for s, _ in steps[index + 1:] if key in s.produces), None)
            if producer is not None:
                raise ValueError(f"{path}: step '{step.name}' reads '{key}', "
                                 f"which '{producer}' produces after it")
        available |= set(step.produces)


def _schema(value: Any, path: Path) -> Schema:
    """The schema a configuration names, in any of the three forms `schema` takes."""
    if isinstance(value, Mapping):
        unknown = set(value) - {"ontologies", "packs", "profile", "shapes"}
        if unknown:
            raise ValueError(f"{path}: schema takes ontologies, profile and shapes; "
                             f"not {', '.join(sorted(unknown))}")
        return load(*_listed(value.get("ontologies") or value.get("packs")),
                    base=path.parent, profile=str(value.get("profile") or ""),
                    shapes=_listed(value.get("shapes")))
    return load(*_listed(value), base=path.parent)


def _listed(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """A configuration key that takes one name or several, always read as several."""
    if not value:
        return ()
    return (value,) if isinstance(value, str) else tuple(value)


def _run_id(*material: Any) -> str:
    """A run is identified by what it is a record of, so a replay carries the id it carried before.

    Nothing is deduplicated: the store appends, as it does with everything else, so two
    identical passes are two rows under one id -- a history saying the pass was repeated,
    which is not the same claim as saying the work was done twice.
    """
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:16]
