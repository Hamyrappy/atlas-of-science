"""The store that keeps everything in the process: a dict and a list.

For tests, for a single pass over a corpus, and as the shortest statement of what
the protocol means. It is append-only like the file store -- `assert_` only ever
grows the log -- so a test that passes here is a test about the semantics and not
about the medium.
"""

from __future__ import annotations

from atlas.model import Assertion, Link, Node, Source
from atlas.store import check_evidence, links_in, nodes_in


class MemoryStore:
    """Sources by id, assertions in the order they arrived, projected on read."""

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._log: list[Assertion] = []

    def add_source(self, source: Source) -> None:
        self._sources[source.id] = source

    def get_source(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)

    def assert_(self, assertion: Assertion) -> None:
        check_evidence(self, assertion)
        self._log.append(assertion)

    def assertions(self, target_id: str | None = None) -> tuple[Assertion, ...]:
        return tuple(a for a in self._log if target_id is None or a.target.id == target_id)

    def nodes(self) -> tuple[Node, ...]:
        return nodes_in(self._log)

    def links(self) -> tuple[Link, ...]:
        return links_in(self._log)

    def by_type(self, type_name: str) -> tuple[Node, ...]:
        return tuple(node for node in self.nodes() if node.type == type_name)
