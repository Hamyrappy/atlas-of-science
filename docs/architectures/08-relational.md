# Architecture 8 — Relational execution of the graph contract

| | |
|---|---|
| **Id** | `a08` |
| **Manifest** | [`architectures/a08.yaml`](../../architectures/a08.yaml) |
| **Family** | Relational traversal |
| **Optimises** | Answering from a large store without reading it |
| **Score** | relevance 88, novelty 78, prospect 88, **total 86** — an engineering judgement, not a measurement |

## 1. What it is for

Every other architecture here reads the store's links into the process and walks them
there. That is the right shape for hundreds of documents and the wrong one at a million
claims: the walk visits forty nodes and the read before it visited the corpus.

This architecture keeps exactly the same record — the same append-only log, the same
metamodel, the same evidence package — and moves the graph read into the database. A
question fetches a bounded neighbourhood; nothing downstream can tell which way the
graph arrived, which is the property that makes this comparable with the others rather
than a different system.

**It needs no model to build the store and no service to run.** `sqlite3` is in the
standard library, so this costs the library no dependency and runs in a test.

## 2. What it is not

It is not a different data model. There is no flattening of the argument into columns:
the same `Node` and `Link` objects are stored whole, and the tables beside them are a
*projection* — a cache of `current` — not a second source of truth.

It is not a silent optimisation either. `graph_expand_sql` refuses a store that cannot
answer its queries, naming what is missing, rather than falling back to reading every
link. A configuration that names this step is asking for the relational route, and
quietly giving it the other one would mean the thing being measured is not the thing that
ran.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core` + `scierc`, unchanged. The SQL schema is derived physical structure and carries no meaning of its own. |
| **Reasoner** | None. What the database computes is reachability, not entailment. |
| **Data** | `assertions` (the log, append-only), `nodes` and `links` (the projection, maintained on write), plus sources, runs and schemas. |
| **Components and reuse** | `sqlite3` with a recursive CTE and `json_each`; the shared `expand`, `Bundle` and `graph_answer`. |
| **Evolution** | A pack change moves `Schema.version` as everywhere; the projection is unaffected, because it stores objects whole rather than columns per field. |

## 4. The store

### 4.1 Tables

| Table | What it holds |
|---|---|
| `assertions` | Every assertion ever made, in order, with its target, kind, time and what it supersedes |
| `nodes` | The projection: one row per currently-claimed node, indexed by type |
| `links` | The projection: one row per currently-claimed link, indexed by both ends |
| `sources`, `runs`, `schemas` | As the protocol requires |

### 4.2 The one invariant that costs something

The projection is maintained **on write**, in the same transaction as the assertion:

```
assert_(a):
    INSERT INTO assertions ...            -- the log, always
    if a.supersedes: DELETE FROM nodes|links WHERE id = (that assertion's target)
    INSERT INTO nodes|links ... ON CONFLICT DO UPDATE WHERE excluded.at >= at
```

Superseding deletes from the **projection** and never from the log. `assertions()` still
returns every assertion ever made, including the superseded one, which is tested
(`test_superseding_moves_the_projection_and_never_the_log`). Writing is still asserting;
what changed is that `current` is precomputed rather than replayed.

That is the bargain that makes the recursive query possible at all — a CTE cannot run
over a log it would have to project first.

### 4.3 The query

```sql
WITH RECURSIVE walk(id, depth) AS (
    SELECT value, 0 FROM json_each(?)
    UNION
    SELECT CASE WHEN links.src = walk.id THEN links.dst ELSE links.src END, walk.depth + 1
    FROM links JOIN walk ON links.src = walk.id OR links.dst = walk.id
    WHERE walk.depth < ?
)
SELECT id, MIN(depth) AS depth FROM walk GROUP BY id ORDER BY depth, id LIMIT ?
```

Three details carry weight:

- **`json_each` for the seeds.** The seed list becomes rows rather than a query string
  built out of it, which is where a store like this usually grows an injection.
- **Both directions in one recursion step.** A relation is asserted one way round and a
  question is not; a directed walk would make the reachable set depend on how an
  extractor phrased the relation.
- **`UNION`, not `UNION ALL`.** That is what terminates a cycle, and extracted graphs
  have cycles because prose does.

One row beyond the limit is fetched so that *"there was more"* can be reported rather
than guessed.

## 5. Pipeline

### 5.1 Build

```
ingest_pdf → extract_llm → relocate → validate → relate_llm → relate → assert → index_nodes
```

Identical to the others. The manifest names the store — `{sqlite: {path: store/atlas.db}}`
— and that is the whole of the difference at build time.

### 5.2 Ask

```
index_nodes → retrieve → graph_expand_sql → graph_answer
```

`graph_expand_sql`:

1. asks the store for `reach(roots, depth, limit)` — the neighbourhood, by query;
2. asks for `links_among(ids)` — the relations inside it;
3. asks for `links_touching(ids, opposes)` — **the objections that reach into it from
   outside**, which is the second query and the reason it exists: a relation whose other
   end the walk never reached is exactly the one a bounded fetch loses;
4. builds an `Adjacency` over just those links and hands it to the same `expand` as
   every other architecture.

The package that comes out is the same `Bundle`, with `method: "graph_expand_sql"` and
`partial` set if either the query's budget or the walk's bound it.
`test_the_two_routes_agree_on_the_same_store` fills a memory store and a SQLite store
with the same content and asserts both routes return the same nodes, links and
objections.

## 6. Competency questions

| Question | How the relational route answers it |
|---|---|
| Which results rest on this dataset, at what remove? | `reach` from the dataset, distances returned by the query |
| Which studies are comparable? | The neighbourhood, then `compare` as in architecture 5 |
| What does the store currently claim? | `nodes()` / `links()` over the projection, without replaying the log |

## 7. Risks and acceptance

- **The projection can drift from the log** if anything writes around `assert_`. Nothing
  does, and the test that proves the log is whole after a supersede is the guard.
- **`links_among` uses one placeholder per id**, which has a ceiling. A neighbourhood is
  bounded by `limit` and stays far below it; a much larger bound wants a temporary table.
- **An index still lives outside the database** — `artifact()` points beside the file.
  That is the same bargain the file store makes.

Acceptance: the two routes must agree on the same content, and the relational one must
still hold the objection under a budget that excludes its far end. Both are tested.

## 8. Running it

```bash
atlas run architectures/a08.yaml corpus/*.pdf
atlas ask architectures/a08.yaml "which results rest on this dataset?"
```

The store is named in the manifest, so `--store` is not needed (and overrides it with a
jsonl store if given, which is a useful way to compare the two).

## 9. Implementation

| Part | Where |
|---|---|
| The store | `atlas/store/sqlite.py` (`SqliteStore`, `REACH`, `links_among`, `links_touching`) |
| Relational retrieval | `atlas/steps/graph_sql.py` |
| Shared packaging | `atlas/steps/graph_expand.py` (`expand`, with a supplied adjacency) |
| Manifest | `architectures/a08.yaml` |
| Tests | `tests/test_sqlite_store.py`, `tests/test_graph_sql.py` |
