# Architecture 14 — Mapped graph over existing tables

| | |
|---|---|
| **Id** | `a14` |
| **Manifest** | [`architectures/a14.yaml`](../../architectures/a14.yaml) |
| **Family** | Mapped traversal |
| **Optimises** | Reading structured data without a round trip through prose |
| **Score** | relevance 68, novelty 74, prospect 82, **total 75** — an engineering judgement, not a measurement |

## 1. What it is for

A table of results is already structured. Rendering it into prose so that a language
model can extract the structure back out is introducing errors on purpose, and paying
for the privilege. What it needs is a **mapping**: this column identifies a study, that
one is the value of a result, and the two are related.

The output is the same typed graph every other architecture produces, under the same
vocabulary, bound to real spans, answered by the same steps. That is the point: a corpus
of papers and a corpus of tables become one graph, and a question crosses between them
without knowing it did.

## 2. What it is not

There is no model on the tabular route at all. Nothing here can hallucinate a condition:
what is not in a column is not in the graph. That is the strength and also the limit —
a table that does not record the protocol contributes no protocol, and architecture 5's
`compare` will report `insufficient`, correctly.

It is also not a generic ETL. The mapping produces objects of an ontology that a formal gate
has checked, and `map_rows` refuses a relation the ontology forbids between two classes, with
the violation reported rather than counted away.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core_ql`, under `profile: QL`, with the `science_core` shapes. The mapping names classes and fields of the ontology, so a mapping and an ontology cannot drift apart silently: a class the ontology does not declare fails `validate`, a relation it forbids is reported, and a mapped record that breaks a shape is refused. |
| **Reasoner** | OWL 2 QL, over the query: the mapped rows go into a SQLite store, and the relations a question is walked over are rewritten by the ontology into SQL (`graph_expand_sql`). SHACL (`shacl_validate`) checks each mapped record in closed world before it is asserted. The mapping itself is executed, not inferred. |
| **Data** | The table, unchanged, as a `Source` whose segments are rendered rows; the graph, in the store, exactly as for any other architecture. |
| **Components and reuse** | `csv` from the standard library, `Span.of`, `Schema.validate_link`. No dependency and no service. |
| **Evolution** | A renamed column or a changed unit is a **mapping revision**. Syntactically valid mapping that still returns numbers is how a unit change goes unnoticed, so the mapping is versioned with the ontology and the old fixtures are re-run. |

## 4. The decision the whole thing rests on

**A row is rendered once, and the rendering is the text layer.**

```
study: S-1 | outcome: yield rose | value: 0.94 | unit: fraction
```

Because of that single decision, everything else in this library works unchanged on a
table. `0.94` is a verbatim substring of its row, so a node built from it is bound by
`Span.of` to a real span, so it can be quoted in an answer, re-verified by
`Span.covers`, superseded by a later assertion, and shipped through a federation whose
integrity check re-slices it. Nothing needed a special case.

Invariant 2 then applies to the rendering: it is fixed at ingest and never produced a
second way, because columns in another order would move every offset under every stored
span. The separators are module constants and changing one changes `Source.text_hash`,
which is the honest consequence.

The header is **not** a segment. Column names travel in `meta`, so a mapping is written
against names: a file that gains a column at the front breaks a positional mapping
silently and a named one loudly. And a row short of a column renders that column empty
rather than dropping it — dropping it would shift the offsets of everything after it.

## 5. The rule that carries `map_rows`

**An empty key never joins.**

A mapping identifies a thing by a column's value. A row where that column is blank
produces **no node**, and therefore no relation, and is counted in `unmapped`.

Letting it through as the empty string is the tempting alternative and it is
catastrophic and quiet: every row missing that column collapses into one node, and every
relation touching it becomes a claim about a thing that does not exist — "these forty
results all came out of the same study", asserted with full provenance, entirely false.
`test_an_empty_key_never_joins` is that case.

Two more rules follow from it:

- **A relation needs both ends in the same row.** Joining across rows means deciding
  which rows belong together, which is a question about the data nobody here can answer.
  A mapping that wants it produces a column that already carries the join.
- **A node is minted once, from the first row that identifies it.** A study named in
  forty rows is one node whose evidence is the first of them. A second row with
  different fields is a mapping to fix or an assertion to supersede — not something to
  average.

## 6. The ontology and the engine

Data that already lives in tables, read through a mapping and queried through an
ontology, is what OWL 2 QL was designed for — the W3C's name for it is ontology-based data
access. The ontology rewrites the question instead of the data being copied into a form
a reasoner can read: a question is a union of plain queries over what the mapping
produced, and the database answers joins without knowing an ontology exists. So this
architecture writes into a **SQLite store** (`store: {sqlite: {path: store/tables.db}}`)
and answers with `graph_expand_sql`, which widens every relation it is given to the
relations `science_core_ql` makes kinds of it — an inverse read the other way round, a
sub-relation — before a query is written. The `query` step takes a conjunctive query
directly for a question that is one:

```
q(?result, ?study) :- StudyResult(?result), produced_by(?result, ?study)
```

and the rewriting also returns a node the ontology makes a `StudyResult` only by the
relations it stands in, as stored rows and never as invented ones.

The table is closed-world material and SHACL is the closed-world check: `shacl_validate`
runs between `validate` and `assert`, with the shapes the ontology implies — each class
closed over its own fields, every mapped node on a span, the classes at each end of each
mapped relation — so a mapping that puts a study where a result should be is refused
with the shape's message before the store sees it, the relation refused and its ends kept.

## 7. Pipeline

```
ingest_table → map_rows → validate → shacl_validate → assert → index_nodes
```

```
index_nodes → retrieve → graph_expand_sql → graph_answer
```

The ask chain is the relational one, and otherwise plain, which is the whole claim of the
architecture: by the time a question arrives there is nothing tabular left, only a store
the ontology can rewrite a question over.

The two routes combine in one store — run `a14` over the tables and a text architecture
over the papers into the same SQLite store, by naming it in both manifests, and the graph
holds both. A
result mapped from a row and a claim extracted from a sentence are related by whatever
relates them.

## 8. Evolution, with the failure to watch for

A source renames a column and changes a unit. The mapping, updated only for the rename,
keeps returning numbers — and they now mean something else. Nothing syntactic catches
this.

What catches it is the fixtures: the mapping travels with example rows and their
expected nodes, and a unit change fails them. When the conversion is genuine,
architecture 5's `Conversion` records the factor and the unit it started from, so the
transformation is an act with provenance rather than an arithmetic detail.

## 9. Competency questions

| Question | What the mapping gives |
|---|---|
| Which results came out of the same study? | `produced_by` from the column that identifies the study — never from a blank |
| Which rows support a published statement? | The span of the row, quotable in an answer |
| What changed between two versions of this table? | Two sources, two text hashes, two sets of nodes under stable identities |

## 10. Risks and acceptance

- **The mapping is the whole quality of the result.** A wrong key column produces a
  confident, well-provenanced, false graph. The empty-key rule removes the commonest
  case; the rest is fixtures.
- **Stable identities are a claim.** `identity(type, key)` says two rows with one key
  are one thing. Where a key is reused across files for different things, that is wrong
  and nothing here can detect it.
- **Tables under-report.** The architecture does not compensate, which is correct and
  looks like poor yield.

Acceptance: rows with a blank key must produce no relation between the things they
mention. If they do, the mapping is not implemented, whatever else works.

## 11. Running it

```bash
atlas run architectures/a14.yaml data/*.csv
atlas ask architectures/a14.yaml "which results came out of the same study?"
```

## 12. Implementation

| Part | Where |
|---|---|
| Rendering rows as a text layer | `atlas/steps/ingest_table.py` (`read_table`, `render`, `cell`) |
| Executing a mapping | `atlas/steps/map_rows.py` (`map_rows`, `NodeMapping`, `LinkMapping`, `identity`) |
| Vocabulary and shapes | `ontologies/science_core_ql.ttl`, `ontologies/shapes/science_core.ttl` |
| Engines | `atlas/reason/ql.py`, `atlas/steps/graph_sql.py`, `atlas/steps/query.py`; `atlas/steps/shacl_validate.py` |
| Manifest | `architectures/a14.yaml` |
| Tests | `tests/test_ingest_table.py`, `tests/test_map_rows.py`, `tests/test_shacl_validate.py`, `tests/test_query.py` |
