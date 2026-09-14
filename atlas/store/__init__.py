"""The write path: a log of assertions, and the graph that is read back out of it.

A store is not a database of nodes. It holds sources and an append-only body of
assertions, and every graph read is the projection `current` makes over that body,
so a re-extraction lands under the judgements already recorded instead of erasing
them. History is only returned when it is asked for, through `assertions`.

The protocol is here, the implementations next to it: one in process, one on disk,
and a third, in a database, will want to push these same reads into queries rather
than inherit anything -- which is why what is shared lives in three free functions
and not in a base class.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from atlas.model import Assertion, Link, Node, Source, current


class Store(Protocol):
    """Somewhere sources and assertions are kept, and a graph is read back."""

    def add_source(self, source: Source) -> None:
        """Record a source. Recording an id twice keeps the later one."""

    def get_source(self, source_id: str) -> Source | None:
        """The source under an id, or None if this store has never held it."""

    def assert_(self, assertion: Assertion) -> None:
        """Append one assertion. Nothing is ever updated or removed."""

    def assertions(self, target_id: str | None = None) -> tuple[Assertion, ...]:
        """The raw history, in the order it was written, for one target or for all."""

    def nodes(self) -> tuple[Node, ...]:
        """The nodes the history projects to: latest per id, nothing superseded."""

    def links(self) -> tuple[Link, ...]:
        """The links the history projects to: latest per id, nothing superseded."""

    def by_type(self, type_name: str) -> tuple[Node, ...]:
        """Projected nodes whose type is written exactly as given.

        The store holds no schema, so this compares terms and does not resolve a
        CURIE or descend a hierarchy; that is `Schema.is_a` over `nodes()`.
        """


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
