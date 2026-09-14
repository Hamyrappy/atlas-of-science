"""The reference implementation of the append-only semantics: files of JSON lines.

Writing is one line appended to `sources.jsonl`, `assertions.jsonl` or `runs.jsonl`,
and nothing else -- no rewrite, no delete, no index to keep in step -- so a crash can
truncate the tail but cannot corrupt what was already written, and the file is the
audit trail rather than a serialisation of one. A schema is a file named by its own
version under `schemas/`, so writing one twice writes the bytes that are already there.

Reads are served from a projection held in memory and keyed on the size and
modification time of the log it was read from. A process that reads far more often
than it writes therefore parses each file once rather than once per read: appending
drops the projection, and so does a write by anyone else, because the stamp moves.
The cache is derived from the log and never consulted for what the log does not say,
which keeps it from disagreeing with the history.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from atlas.model import Assertion, Link, Node, Run, Schema, Source
from atlas.store import check_evidence, links_in, nodes_in, register_store

Stamp = tuple[int, int]


@dataclass(frozen=True)
class _Graph:
    """One parse of one assertion log, and the stamp of the file it was parsed from."""

    stamp: Stamp
    assertions: tuple[Assertion, ...]
    nodes: dict[str, Node]
    links: tuple[Link, ...]


class JsonlStore:
    """A directory of append-only logs, with the projection cached beside them."""

    def __init__(self, directory: Path | str) -> None:
        self.location = Path(directory)
        self.location.mkdir(parents=True, exist_ok=True)
        self.sources_path = self.location / "sources.jsonl"
        self.assertions_path = self.location / "assertions.jsonl"
        self.runs_path = self.location / "runs.jsonl"
        self.schemas_dir = self.location / "schemas"
        self._read_sources: tuple[Stamp, dict[str, Source]] | None = None
        self._read_graph: _Graph | None = None

    def add_source(self, source: Source) -> None:
        _append(self.sources_path, source)
        self._read_sources = None

    def get_source(self, source_id: str) -> Source | None:
        """The last source written under the id: an append is how a reparse lands."""
        return self._sources().get(source_id)

    def sources(self) -> tuple[Source, ...]:
        return tuple(self._sources().values())

    def assert_(self, assertion: Assertion) -> None:
        check_evidence(self, assertion)
        _append(self.assertions_path, assertion)
        self._read_graph = None

    def assertions(self, target_id: str | None = None) -> tuple[Assertion, ...]:
        log = self._graph().assertions
        return log if target_id is None else tuple(a for a in log if a.target.id == target_id)

    def nodes(self) -> tuple[Node, ...]:
        return tuple(self._graph().nodes.values())

    def links(self) -> tuple[Link, ...]:
        return self._graph().links

    def get_node(self, node_id: str) -> Node | None:
        return self._graph().nodes.get(node_id)

    def get_nodes(self, ids: Iterable[str]) -> tuple[Node, ...]:
        nodes = self._graph().nodes
        return tuple(found for found in map(nodes.get, ids) if found is not None)

    def by_type(self, type_name: str) -> tuple[Node, ...]:
        return tuple(node for node in self.nodes() if node.type == type_name)

    def artifact(self, name: str) -> Path | None:
        """Somewhere under this directory; the file itself is the caller's business."""
        return self.location / name

    def add_run(self, run: Run) -> None:
        _append(self.runs_path, run)

    def runs(self) -> tuple[Run, ...]:
        return _read(self.runs_path, Run)

    def add_schema(self, schema: Schema) -> None:
        """One file per version: the same version twice is the file that is already there."""
        self.schemas_dir.mkdir(parents=True, exist_ok=True)
        path = self.schemas_dir / f"{schema.version}.json"
        if not path.exists():
            path.write_text(schema.model_dump_json(), encoding="utf-8")

    def get_schema(self, version: str) -> Schema | None:
        path = self.schemas_dir / f"{version}.json"
        if not path.exists():
            return None
        return Schema.model_validate_json(path.read_text(encoding="utf-8"))

    def _sources(self) -> dict[str, Source]:
        stamp = _stamp(self.sources_path)
        if self._read_sources is None or self._read_sources[0] != stamp:
            written = _read(self.sources_path, Source)
            self._read_sources = (stamp, {source.id: source for source in written})
        return self._read_sources[1]

    def _graph(self) -> _Graph:
        stamp = _stamp(self.assertions_path)
        if self._read_graph is None or self._read_graph.stamp != stamp:
            log = _read(self.assertions_path, Assertion)
            nodes = {node.id: node for node in nodes_in(log)}
            self._read_graph = _Graph(stamp, log, nodes, links_in(log))
        return self._read_graph


@register_store("jsonl")
def open_jsonl(base: Path | None = None, **options: Any) -> JsonlStore:
    """`{jsonl: {dir: store}}`: a directory of logs, resolved against the configuration."""
    directory = Path(options.get("dir", "store"))
    return JsonlStore(directory if base is None else base / directory)


def _stamp(path: Path) -> Stamp:
    """What a file looks like from outside -- size and mtime -- in one `stat` per read."""
    try:
        status = path.stat()
    except FileNotFoundError:
        return (0, 0)
    return (status.st_size, status.st_mtime_ns)


def _append(path: Path, value: BaseModel) -> None:
    with path.open("a", encoding="utf-8") as out:
        out.write(value.model_dump_json() + "\n")


def _read[T: BaseModel](path: Path, kind: type[T]) -> tuple[T, ...]:
    if not path.exists():
        return ()
    with path.open(encoding="utf-8") as lines:
        return tuple(kind.model_validate_json(line) for line in lines if line.strip())
