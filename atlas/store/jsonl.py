"""The reference implementation of the append-only semantics: two files of JSON lines.

Writing is one line appended to `sources.jsonl` or `assertions.jsonl`, and nothing
else -- no rewrite, no delete, no index to keep in step -- so a crash can truncate
the tail but cannot corrupt what was already written, and the file is the audit
trail rather than a serialisation of one. Every read parses both files and projects
them again, which is the price of holding no state and is paid on a corpus, not on
a request.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from atlas.model import Assertion, Link, Node, Source
from atlas.store import check_evidence, links_in, nodes_in


class JsonlStore:
    """A directory of append-only logs; the projection is computed on every read."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.sources_path = self.directory / "sources.jsonl"
        self.assertions_path = self.directory / "assertions.jsonl"

    def add_source(self, source: Source) -> None:
        _append(self.sources_path, source)

    def get_source(self, source_id: str) -> Source | None:
        """The last source written under the id: an append is how a reparse lands."""
        written = _read(self.sources_path, Source)
        return next((s for s in reversed(written) if s.id == source_id), None)

    def assert_(self, assertion: Assertion) -> None:
        check_evidence(self, assertion)
        _append(self.assertions_path, assertion)

    def assertions(self, target_id: str | None = None) -> tuple[Assertion, ...]:
        log = _read(self.assertions_path, Assertion)
        return tuple(a for a in log if target_id is None or a.target.id == target_id)

    def nodes(self) -> tuple[Node, ...]:
        return nodes_in(self.assertions())

    def links(self) -> tuple[Link, ...]:
        return links_in(self.assertions())

    def by_type(self, type_name: str) -> tuple[Node, ...]:
        return tuple(node for node in self.nodes() if node.type == type_name)


def _append(path: Path, value: BaseModel) -> None:
    with path.open("a", encoding="utf-8") as out:
        out.write(value.model_dump_json() + "\n")


def _read[T: BaseModel](path: Path, kind: type[T]) -> tuple[T, ...]:
    if not path.exists():
        return ()
    with path.open(encoding="utf-8") as lines:
        return tuple(kind.model_validate_json(line) for line in lines if line.strip())
