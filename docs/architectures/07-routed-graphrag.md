# Architecture 7 — Routed scientific GraphRAG

| | |
|---|---|
| **Id** | `a07` |
| **Manifest** | [`architectures/a07.yaml`](../../architectures/a07.yaml) |
| **Family** | Routed traversal |
| **Optimises** | Not answering three kinds of question with one retriever |
| **Score** | relevance 92, novelty 90, prospect 95, **total 93** — an engineering judgement, not a measurement |

## 1. What it is for

Three questions arrive at the same system and want three different things:

- *What exactly did this study show?* — the neighbourhood of one thing.
- *Which directions use similar methods?* — a longer walk across typed relations.
- *How has this field moved?* — a whole region, and answering it from the top-ranked
  passages produces a summary of whatever the ranking happened to like.

One retriever answers at most one of them well. This architecture chooses first and then
retrieves, and what the choice changes is **which seeds the walk starts from and how
many** — never whether the graph is walked, which is not in question anywhere in this
library.

## 2. What it is not

There is no text-only route. The overview route is not "summarise the top passages": it
takes *whole communities*, capped, and says when the cap bound it. And a community
report is not evidence — see §5, which is the design decision this architecture turns on.

It is also not a general-purpose planner. The router picks a *family* of computation;
which operations run inside that family is fixed by the manifest. Architecture 20 is the
one that composes operations per question.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core` + `scierc`. Unchanged by routing: the routes differ in retrieval, not in what is recorded. |
| **Reasoner** | None. The router is markers first, one bounded model call at most. |
| **Data** | The store as everywhere else. Communities and reports are computed per question and never asserted. |
| **Components and reuse** | Greedy modularity agglomeration for the partition; the shared `Bundle`, `graph_expand` and `graph_answer` for all three routes. |
| **Evolution** | A route that keeps being wrong is a marker set to fix or a model call to enable; a report that keeps missing something is a relation the partition should follow. Neither is a schema change. |

## 4. Pipeline

### 4.1 Build

The ordinary chain. Routing is a property of asking, not of building:

```
ingest_pdf → extract_llm → relocate → validate → relate_llm → relate → assert → index_nodes
```

### 4.2 Ask

```
index_nodes → route → communities → retrieve_routed → graph_expand → graph_answer → check_answer
```

**`route`** matches the configured markers against the question, in the order the routes
are declared, and returns the route with the marker that chose it. Only if nothing
matched *and* `ask_model` is set is the model asked, with the routes as an enum, and a
reply naming something that is not on offer falls through to the default. Every outcome
carries `route_reason`, so a run can be asked why a question went where it went.

The markers are the configuration's words. They are words of a language and this package
holds none: with nothing configured, every question takes the default route, which is
stated rather than discovered.

**`communities`** partitions the projected graph by greedy modularity agglomeration —
every node in its own community, merge the connected pair whose merge raises modularity
most, stop when no merge would. Label propagation was tried first and is what the module
warns about: on a graph of a few dozen nodes it collapses everything into one community,
which is a true partition and a useless one.

**`retrieve_routed`** seeds the walk:

| Route | Seeds |
|---|---|
| anything but the overview | the top `limit` nodes by term overlap |
| the overview | *every* member of the best `communities` regions, up to `cap` |

`route_capped` is true when the cap bound the overview. A question about how much of a
field does something is a question about a set, and a run that silently answered it from
a sample would be answering a different question.

## 5. The rule that makes an overview honest

**A community report is derived text and is not a node.** It has no span, it is never
asserted, and `graph_answer` only accepts citations that resolve to nodes of the
package. So a generator physically cannot cite the summary in place of the studies it
summarises — not because it is instructed not to, but because the reference does not
resolve and the line is dropped.

That is the whole of the "a summary is not a second study" rule, enforced by the type of
the object rather than by a prompt.

**Invalidation is not a problem here, and the reason is worth stating.** Communities are
recomputed per question from the store's current projection. A superseded study stops
being projected, so the next report simply does not contain it. There is no cache to
remember to clear, because the store is append-only and the projection is a function of
it.

## 6. Graph retrieval, exactly

```
question
  → route: markers in declared order → (model, if asked and nothing matched) → default
  → communities: greedy modularity over the projected graph
  → seeds:
      fact / connections : top-k by term overlap
      overview           : all members of the best regions, capped, capping reported
  → graph_expand: depth 3, budget 80, supports/opposes named
  → graph_answer → check_answer
```

Note that all three routes end in the same two steps. That is deliberate: one evidence
package, one answering contract, one review. The routes differ where they should differ
and nowhere else.

## 7. Evolution

New papers connect two previously separate regions. The partition changes on the next
question and the reports change with it — and **that is not a schema change**. Only a
distinction that survives definition, a reuse check and the competency questions becomes
one, which is architecture 4's machinery and is deliberately not wired into this one.

A route that is consistently wrong is diagnosed from `route_reason` over a batch of
questions: either a marker is missing, or the markers cannot decide this corpus's
questions and `ask_model` should be on.

## 8. Competency questions

| Question | Route | What it needs |
|---|---|---|
| What did study A show? | fact | The neighbourhood, with both sides |
| Which directions use similar methods? | connections | A longer typed walk |
| How has this field moved? | overview | Whole regions, with coverage stated |

## 9. Risks and acceptance

- **Router regret.** Measure it: run every question through every route and compare the
  answers with the route actually chosen. A router that is worse than always choosing
  one route is a router to delete.
- **Most moving parts of any architecture here.** A partition to recompute, three
  behaviours to keep honest, a model call that may or may not happen.
- **Coverage is not consensus.** A community holding most of a corpus says the corpus
  talks about one thing, not that the thing is established.

Acceptance: the overview route must never report a conclusion that only exists in a
report. Check it by citation — every line of an overview answer must cite nodes, and
`check_answer` must show no omitted side.

## 10. Running it

```bash
atlas run architectures/a07.yaml corpus/*.pdf --store store/
atlas ask architectures/a07.yaml "how has this field moved?" --store store/
```

## 11. Implementation

| Part | Where |
|---|---|
| Routing | `atlas/steps/route.py` (`route`, `retrieve_routed`) |
| Partition and reports | `atlas/steps/communities.py` (`communities`, `partition`) |
| Shared walk and answer | `atlas/steps/graph_expand.py`, `atlas/steps/graph_answer.py`, `atlas/steps/check_answer.py` |
| Manifest | `architectures/a07.yaml` |
| Tests | `tests/test_route.py`, `tests/test_communities.py` |
