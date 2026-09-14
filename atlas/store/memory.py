"""The store that keeps everything in the process: dicts and a list.

For tests, for a single pass over a corpus, and as the shortest statement of what
the protocol means. It is append-only like the file store -- `assert_` only ever
grows the log -- so a test that passes here is a test about the semantics and not
about the medium. The projection is computed on the first read after a write and
kept until the next one, which is the same bargain the file store makes.

It lives nowhere, so `location` and `artifact` answer None rather than leaving a
consumer to guess: a step that wants to keep a derived file asks, is told there is
nowhere, and rebuilds instead of reaching into an implementation it was not handed.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from atlas.model import Assertion, Link, Node, Run, Schema, Source
from atlas.store import check_evidence, links_in, nodes_in, register_store


class MemoryStore:
    """Sources by id, assertions in the order they arrived, projected on read."""

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._log: list[Assertion] = []
        self._runs: list[Run] = []
        self._schemas: dict[str, Schema] = {}
        self._projected: tuple[dict[str, Node], tuple[Link, ...]] | None = None

    def add_source(self, source: Source) -> None:
        self._sources[source.id] = source

    def get_source(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)

    def sources(self) -> tuple[Source, ...]:
        return tuple(self._sources.values())

    def assert_(self, assertion: Assertion) -> None:
        check_evidence(self, assertion)
        self._log.append(assertion)
        self._projected = None

    def assertions(self, target_id: str | None = None) -> tuple[Assertion, ...]:
        return tuple(a for a in self._log if target_id is None or a.target.id == target_id)

    def nodes(self) -> tuple[Node, ...]:
        return tuple(self._graph()[0].values())

    def links(self) -> tuple[Link, ...]:
        return self._graph()[1]

    def get_node(self, node_id: str) -> Node | None:
        return self._graph()[0].get(node_id)

    def get_nodes(self, ids: Iterable[str]) -> tuple[Node, ...]:
        nodes = self._graph()[0]
        return tuple(found for found in map(nodes.get, ids) if found is not None)

    def by_type(self, type_name: str) -> tuple[Node, ...]:
        return tuple(node for node in self.nodes() if node.type == type_name)

    @property
    def location(self) -> Path | None:
        """Nowhere: this store is the process it runs in."""
        return None

    def artifact(self, name: str) -> Path | None:
        """Nowhere to put one, which is the honest answer and not an omission."""
        return None

    def add_run(self, run: Run) -> None:
        self._runs.append(run)

    def runs(self) -> tuple[Run, ...]:
        return tuple(self._runs)

    def add_schema(self, schema: Schema) -> None:
        self._schemas.setdefault(schema.version, schema)

    def get_schema(self, version: str) -> Schema | None:
        return self._schemas.get(version)

    def _graph(self) -> tuple[dict[str, Node], tuple[Link, ...]]:
        if self._projected is None:
            log = tuple(self._log)
            self._projected = ({n.id: n for n in nodes_in(log)}, links_in(log))
        return self._projected


@register_store("memory")
def open_memory(base: Path | None = None, **options: Any) -> MemoryStore:
    """`memory`: a store that starts empty and is gone when the process is."""
    return MemoryStore()
