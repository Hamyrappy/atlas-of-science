"""The store that keeps the log in SQLite, and pushes the graph reads into queries.

The other two stores project the whole assertion log in the process: fine for a corpus
of hundreds, and the wrong shape once a question has to be answered from a store of
millions of claims without reading all of them first. This one keeps the same
append-only log -- nothing is ever updated or deleted, a correction is a new assertion
naming the one it supersedes -- and keeps a projection of it in two ordinary tables
beside it, so a graph read is a query.

The projection is maintained on write rather than recomputed on read, which is the
bargain that makes `reach` possible at all: a recursive CTE cannot run over a log it
would have to replay first. `assert_` writes the assertion and updates the projection in
one transaction, so the two cannot disagree; superseding is a delete from the
*projection* and never from the log, which still holds every assertion ever made.

`reach` is what this store exists for. It walks the link table from a set of seeds to a
bounded depth inside the database, in both directions, and returns the ids and how far
each one was -- so `graph_expand_sql` can build an evidence package by fetching the
neighbourhood rather than the corpus. It is an addition to the protocol, not part of it:
a consumer asks for it with `getattr` and falls back to reading the links, which is
exactly what the other two stores will make it do.

Standard library only: `sqlite3` ships with Python, so a relational architecture costs
this library no dependency and runs in a test with no service to start.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

from atlas.model import Assertion, Link, Node, Run, Schema, Source
from atlas.store import check_evidence, register_store

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assertions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL,
    at TEXT NOT NULL, supersedes TEXT, body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assertions_target ON assertions (target_id);
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, at TEXT NOT NULL, body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS nodes_type ON nodes (type);
CREATE TABLE IF NOT EXISTS links (
    id TEXT PRIMARY KEY, predicate TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL,
    at TEXT NOT NULL, body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS links_src ON links (src);
CREATE INDEX IF NOT EXISTS links_dst ON links (dst);
CREATE TABLE IF NOT EXISTS runs (seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schemas (version TEXT PRIMARY KEY, body TEXT NOT NULL);
"""

REACH = """
WITH RECURSIVE walk(id, depth) AS (
    SELECT value, 0 FROM json_each(?)
    UNION
    SELECT CASE WHEN links.src = walk.id THEN links.dst ELSE links.src END, walk.depth + 1
    FROM links JOIN walk ON links.src = walk.id OR links.dst = walk.id
    WHERE walk.depth < ?
)
SELECT id, MIN(depth) AS depth FROM walk GROUP BY id ORDER BY depth, id LIMIT ?
"""
"""Every node within `depth` links of the seeds, nearest first.

`json_each` turns the seed list into rows without building a query string out of them,
which is the one place a store like this usually grows an injection. Both directions are
walked in one step of the recursion, because a relation is asserted one way round and a
question is not. `UNION` rather than `UNION ALL` is what stops a cycle."""


class Reached(NamedTuple):
    """What the database found: the node ids by distance, and whether the budget bound it."""

    distances: dict[str, int]
    partial: bool


class SqliteStore:
    """An append-only log and its projection, in one file or in memory.

    Costs, in the terms `Store` states them: `get_source`, `get_node` and `add_source`
    are indexed lookups rather than O(1) dictionary reads, which is the same promise at
    a larger constant. `nodes()` and `links()` are O(k) over the projection and not over
    the log, which is the point. `assertions()` is O(m) as everywhere.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.location = Path(path) if path is not None else None
        if self.location is not None:
            self.location.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.location) if self.location else ":memory:")
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    # ---- sources ------------------------------------------------------------------
    def add_source(self, source: Source) -> None:
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO sources (id, body) VALUES (?, ?)",
                             (source.id, source.model_dump_json()))

    def get_source(self, source_id: str) -> Source | None:
        row = self._db.execute("SELECT body FROM sources WHERE id = ?", (source_id,)).fetchone()
        return Source.model_validate_json(row["body"]) if row else None

    def sources(self) -> tuple[Source, ...]:
        rows = self._db.execute("SELECT body FROM sources ORDER BY rowid").fetchall()
        return tuple(Source.model_validate_json(row["body"]) for row in rows)

    # ---- the log and its projection -------------------------------------------------
    def assert_(self, assertion: Assertion) -> None:
        """Append the assertion and move the projection with it, in one transaction.

        The projection is a cache of `current` and nothing more: the assertion goes into
        the log whatever happens to it, and what a superseding assertion removes is the
        row in `nodes` or `links`, never a row in `assertions`.
        """
        check_evidence(self, assertion)
        target = assertion.target
        kind = "link" if isinstance(target, Link) else "node"
        with self._db:
            self._db.execute(
                "INSERT INTO assertions (id, target_id, kind, at, supersedes, body) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (assertion.id, target.id, kind, assertion.at, assertion.supersedes,
                 assertion.model_dump_json()),
            )
            if assertion.supersedes:
                self._retire(assertion.supersedes)
            if kind == "node":
                self._db.execute(
                    "INSERT INTO nodes (id, type, at, body) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET type = excluded.type, at = excluded.at, "
                    "body = excluded.body WHERE excluded.at >= nodes.at",
                    (target.id, target.type, assertion.at, target.model_dump_json()),
                )
            else:
                self._db.execute(
                    "INSERT INTO links (id, predicate, src, dst, at, body) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET at = excluded.at, body = excluded.body "
                    "WHERE excluded.at >= links.at",
                    (target.id, target.predicate, target.src, target.dst, assertion.at,
                     target.model_dump_json()),
                )

    def assertions(self, target_id: str | None = None) -> tuple[Assertion, ...]:
        if target_id is None:
            rows = self._db.execute("SELECT body FROM assertions ORDER BY seq").fetchall()
        else:
            rows = self._db.execute(
                "SELECT body FROM assertions WHERE target_id = ? ORDER BY seq", (target_id,)
            ).fetchall()
        return tuple(Assertion.model_validate_json(row["body"]) for row in rows)

    def nodes(self) -> tuple[Node, ...]:
        rows = self._db.execute("SELECT body FROM nodes ORDER BY rowid").fetchall()
        return tuple(Node.model_validate_json(row["body"]) for row in rows)

    def links(self) -> tuple[Link, ...]:
        rows = self._db.execute("SELECT body FROM links ORDER BY rowid").fetchall()
        return tuple(Link.model_validate_json(row["body"]) for row in rows)

    def get_node(self, node_id: str) -> Node | None:
        row = self._db.execute("SELECT body FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return Node.model_validate_json(row["body"]) if row else None

    def get_nodes(self, ids: Iterable[str]) -> tuple[Node, ...]:
        wanted = list(ids)
        if not wanted:
            return ()
        rows = self._db.execute(
            "SELECT id, body FROM nodes WHERE id IN "
            f"({','.join('?' * len(wanted))})", wanted
        ).fetchall()
        held = {row["id"]: Node.model_validate_json(row["body"]) for row in rows}
        return tuple(held[node_id] for node_id in wanted if node_id in held)

    def by_type(self, type_name: str) -> tuple[Node, ...]:
        rows = self._db.execute(
            "SELECT body FROM nodes WHERE type = ? ORDER BY rowid", (type_name,)
        ).fetchall()
        return tuple(Node.model_validate_json(row["body"]) for row in rows)

    # ---- the read this store exists for ----------------------------------------------
    def reach(self, seeds: Iterable[str], depth: int = 2, limit: int = 200) -> Reached:
        """The ids within `depth` links of the seeds, nearest first, computed in the database.

        Not part of the `Store` protocol: a consumer asks for it with `getattr` and
        reads `links()` when it is not there. One extra row is fetched beyond the limit
        so that "there was more" can be reported rather than guessed.
        """
        wanted = list(dict.fromkeys(seeds))
        if not wanted:
            return Reached({}, False)
        rows = self._db.execute(
            REACH, (json.dumps(wanted), max(depth, 0), limit + 1)
        ).fetchall()
        distances = {row["id"]: row["depth"] for row in rows[:limit]}
        return Reached(distances, len(rows) > limit)

    def links_among(self, ids: Iterable[str]) -> tuple[Link, ...]:
        """Every projected link with both ends inside a set of ids, in id order."""
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return ()
        holes = ",".join("?" * len(wanted))
        rows = self._db.execute(
            f"SELECT body FROM links WHERE src IN ({holes}) AND dst IN ({holes}) ORDER BY id",
            wanted + wanted,
        ).fetchall()
        return tuple(Link.model_validate_json(row["body"]) for row in rows)

    def links_touching(
        self, ids: Iterable[str], predicates: Iterable[str] = ()
    ) -> tuple[Link, ...]:
        """Every projected link with at least one end in a set of ids, optionally by predicate.

        What an objection needs: a relation whose other end the walk never reached is
        exactly the one a budget would have lost, and it has to be findable without
        reading every link in the store.
        """
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return ()
        holes = ",".join("?" * len(wanted))
        named = list(predicates)
        clause = f" AND predicate IN ({','.join('?' * len(named))})" if named else ""
        rows = self._db.execute(
            f"SELECT body FROM links WHERE (src IN ({holes}) OR dst IN ({holes})){clause} "
            "ORDER BY id",
            wanted + wanted + named,
        ).fetchall()
        return tuple(Link.model_validate_json(row["body"]) for row in rows)

    def select(self, sql: str, params: Iterable[object] = ()) -> list[tuple]:
        """Rows of a read-only query over the projection: what a rewritten query runs as.

        The OWL 2 QL engine rewrites an ontological question into plain joins over `nodes`
        and `links`, and this is where they execute -- which is the point of the relational
        architecture. Anything but a single SELECT (or a WITH leading to one) is refused:
        the store is append-only, and a read seam that could write would not be.
        """
        statement = sql.strip().rstrip(";")
        head = statement.split(None, 1)[0].upper() if statement else ""
        if head not in ("SELECT", "WITH") or ";" in statement:
            raise ValueError("only a single read-only SELECT runs through `select`")
        return [tuple(row) for row in self._db.execute(statement, list(params)).fetchall()]

    # ---- everything else the protocol asks for ----------------------------------------
    def artifact(self, name: str) -> Path | None:
        """Beside the database file; a store held in memory has nowhere and says so."""
        return None if self.location is None else self.location.parent / name

    def add_run(self, run: Run) -> None:
        with self._db:
            self._db.execute("INSERT INTO runs (body) VALUES (?)", (run.model_dump_json(),))

    def runs(self) -> tuple[Run, ...]:
        rows = self._db.execute("SELECT body FROM runs ORDER BY seq").fetchall()
        return tuple(Run.model_validate_json(row["body"]) for row in rows)

    def add_schema(self, schema: Schema) -> None:
        with self._db:
            self._db.execute("INSERT OR IGNORE INTO schemas (version, body) VALUES (?, ?)",
                             (schema.version, schema.model_dump_json()))

    def get_schema(self, version: str) -> Schema | None:
        row = self._db.execute(
            "SELECT body FROM schemas WHERE version = ?", (version,)
        ).fetchone()
        return Schema.model_validate_json(row["body"]) if row else None

    def close(self) -> None:
        self._db.close()

    def _retire(self, assertion_id: str) -> None:
        """Take what a superseded assertion claimed out of the projection, not out of the log."""
        row = self._db.execute(
            "SELECT target_id, kind FROM assertions WHERE id = ?", (assertion_id,)
        ).fetchone()
        if row is None:
            return
        table = "links" if row["kind"] == "link" else "nodes"
        self._db.execute(f"DELETE FROM {table} WHERE id = ?", (row["target_id"],))


@register_store("sqlite")
def open_sqlite(base: Path | None = None, **options: Any) -> SqliteStore:
    """`{sqlite: {path: store/atlas.db}}`, or `{sqlite: {}}` for one held in memory."""
    path = options.get("path")
    if path is None:
        return SqliteStore(None)
    resolved = Path(path)
    return SqliteStore(resolved if base is None else base / resolved)
