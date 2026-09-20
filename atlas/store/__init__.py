"""The write path: a log of assertions, and the graph that is read back out of it.

A store is not a database of nodes. It holds sources and an append-only body of
assertions, and every graph read is the projection `current` makes over that body,
so a re-extraction lands under the judgements already recorded instead of erasing
them. History is only returned when it is asked for, through `assertions`. Beside
that history it keeps two things that are about the history rather than in it: the
runs that wrote it, and the schemas their objects name, so a reader can recover the
vocabulary a stored `schema_version` was written under instead of assuming one.

Every read states its cost, because a store is read from a request handler as well as
from a batch job: an implementation whose cost is worse than the one written here
must say so on its own method, and a consumer may then plan for it.

The protocol is here, the implementations next to it: a third, in a database, will
want to push these same reads into queries rather than inherit anything, which is why
what is shared lives in free functions and not in a base class. Stores are registered
by name the way steps are, so a configuration names one and `open_store` opens it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol

from atlas.model import Assertion, Link, Node, Run, Schema, Source, current


class Store(Protocol):
    """Somewhere sources, assertions, runs and schemas are kept, and a graph is read back.

    Costs are per call, in `n` sources held, `m` assertions written and `k` nodes the
    history currently projects to. A store that keeps its projection in step with its
    log meets them; one that recomputes the projection per call does not.
    """

    def add_source(self, source: Source) -> None:
        """Record a source. Recording an id twice keeps the later one."""

    def get_source(self, source_id: str) -> Source | None:
        """The source under an id, or None if this store has never held it. O(1)."""

    def sources(self) -> tuple[Source, ...]:
        """Every source held, in the order the ids were first written. O(n)."""

    def assert_(self, assertion: Assertion) -> None:
        """Append one assertion. Nothing is ever updated or removed."""

    def assertions(self, target_id: str | None = None) -> tuple[Assertion, ...]:
        """The raw history, in the order it was written, for one target or for all. O(m)."""

    def nodes(self) -> tuple[Node, ...]:
        """The nodes the history projects to: latest per id, nothing superseded. O(k)."""

    def links(self) -> tuple[Link, ...]:
        """The links the history projects to: latest per id, nothing superseded. O(k)."""

    def get_node(self, node_id: str) -> Node | None:
        """The node an id currently projects to, or None if nothing does. O(1)."""

    def get_nodes(self, ids: Iterable[str]) -> tuple[Node, ...]:
        """Those of these ids that project to a node, in the order given. O(ids)."""

    def by_type(self, type_name: str) -> tuple[Node, ...]:
        """Projected nodes whose type is written exactly as given. O(k).

        The store holds no schema, so this compares terms and does not resolve a
        CURIE or descend a hierarchy; that is `Schema.is_a` over `nodes()`.
        """

    @property
    def location(self) -> Path | None:
        """Where this store lives, or None for one that lives nowhere. O(1)."""

    def artifact(self, name: str) -> Path | None:
        """A path a derived artifact may use, or None if this store has nowhere to put one.

        The store neither creates nor reads the file: it only says where one may go, so
        a step that builds an index has somewhere to keep it without knowing the medium.
        """

    def add_run(self, run: Run) -> None:
        """Record what one pass cost. Runs accumulate like assertions; none is replaced."""

    def runs(self) -> tuple[Run, ...]:
        """Every run recorded, in the order they were written. O(runs)."""

    def add_schema(self, schema: Schema) -> None:
        """Keep a schema under its version. Writing the same version twice is a no-op."""

    def get_schema(self, version: str) -> Schema | None:
        """The schema a stored `schema_version` names, or None if it was never kept. O(1)."""


StoreFactory = Callable[..., Store]

_STORES: dict[str, StoreFactory] = {}


def register_store(name: str) -> Callable[[StoreFactory], StoreFactory]:
    """Register a factory under the name a configuration may open it by."""

    def bind(factory: StoreFactory) -> StoreFactory:
        _STORES[name] = factory
        return factory

    return bind


def open_store(spec: str | Mapping[str, Any], base: Path | None = None) -> Store:
    """Open the store a specification names: `"memory"`, or `{"jsonl": {"dir": "store"}}`.

    A bare name takes the factory's defaults; a mapping is that name with its options,
    exactly as a step is named with its options. Paths among the options are resolved
    against `base`, so a configuration and the store it names travel together.
    """
    name, options = (spec, {}) if isinstance(spec, str) else _one(spec)
    if name not in _STORES:
        raise ValueError(f"unknown store {name!r}; registered: {', '.join(sorted(_STORES))}")
    return _STORES[name](base, **options)


def _one(spec: Mapping[str, Any]) -> tuple[str, dict]:
    if len(spec) != 1:
        raise ValueError(f"a store is one name with its options, not {sorted(spec)}")
    [(name, options)] = spec.items()
    return name, options or {}


def nodes_in(assertions: Iterable[Assertion]) -> tuple[Node, ...]:
    """The nodes a body of assertions currently claims."""
    return tuple(target for target in current(assertions) if isinstance(target, Node))


def links_in(assertions: Iterable[Assertion]) -> tuple[Link, ...]:
    """The links a body of assertions currently claims."""
    return tuple(target for target in current(assertions) if isinstance(target, Link))


def check_evidence(store: Store, assertion: Assertion) -> None:
    """Refuse an assertion whose evidence points at a source the store does not hold.

    The model guarantees that every target carries a span, and that all its spans
    come from one source; only a store can say whether that source was ever read.
    Without this check a store accumulates provenance that cannot be re-verified.
    """
    source_id = assertion.target.spans[0].source_id
    if store.get_source(source_id) is None:
        raise KeyError(f"assertion {assertion.id} stands on unknown source {source_id}")


from atlas.store import jsonl, memory, sqlite  # noqa: E402, F401
