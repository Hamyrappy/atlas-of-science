# Architecture 20 — Answering by a plan of typed graph operators

| | |
|---|---|
| **Id** | `a20` |
| **Manifest** | [`architectures/a20.yaml`](../../architectures/a20.yaml) |
| **Family** | Logical-form execution |
| **Optimises** | A compound question, where composing inside the prose is where it goes wrong |
| **Score** | relevance 90, novelty 93, prospect 94, **total 92** — an engineering judgement, not a measurement |

## 1. What it is for

> *Which methods improved the result under the same protocol, were reproduced
> independently, and have no strong refutation?*

That is not one retrieval. It is a composition: resolve some things, traverse to what was
found about them, filter to the comparable ones, count the independent confirmations,
bring in what argues the other way. Every other architecture here answers it by
retrieving a neighbourhood and hoping the model composes correctly inside the prose.

This one makes the composition explicit: a plan of typed operations, checked before it
runs, executed step by step, with the witnesses of each step kept.

## 2. What it is not

It is not a reasoner. The operators are graph operations — reachability, selection,
counting, grouping — and nothing in the language computes an entailment. Architecture 10
does that, and a plan can run over what it materialised.

It is also not an open language. Seven operators, all read-only, and nothing that could
write to a store. A language with an escape hatch would have nothing to type-check, and
the type check is the whole reason a generated plan is safe to execute.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core_ql` + `process` + `scierc_ql`, under `profile: QL`. The ontology is what the plan is checked against, and what rewrites each operator before it runs. |
| **Reasoner** | OWL 2 QL, over the plan: `resolve` of a class and `traverse` of a relation are each rewritten by the ontology into the union of queries over what is stored, run as SQL where the store can, and each step keeps its rewriting in the trace. The type check is a lookup; nothing is materialised. |
| **Data** | The store; the trace kept per question. |
| **Components and reuse** | `Adjacency`, `Schema.find_predicate` / `find_type` / `is_a`, `atlas.text` for matching, the shared `expand`. |
| **Evolution** | A plan that cannot be expressed names the gap: a relation the ontology lacks, a field nothing fills, or data nobody extracted. The trace says which, and only the first is a schema change. |

## 4. The ontology and the engine

A plan is a conjunctive query written one operator at a time, and OWL 2 QL is the profile
whose ontologies answer conjunctive queries by rewriting them. So each operator is
rewritten before it runs:

- **`resolve` of a class** is the query `C(?x)`, rewritten by `atlas/reason/ql.py` into
  every stored way of being a C — each subclass, and each relation whose domain or range
  makes its subject or object one — and answered by `SqliteStore.select` where the store
  runs SQL, in memory otherwise. The answers are joined with the classified hierarchy's,
  and both are sound, so their union is.
- **`traverse` of a relation** crosses every relation the ontology makes a kind of it, each
  in the direction the ontology says: an inverse is crossed backwards.

The manifest loads `process` beside `science_core_ql`, and it shows in the trace: the
process ontology declares `obtained_under` a kind of `observed_under`, so the plan's
`traverse(observed_under)` also crosses it. Each executed step records the rewriting it
ran, which is how a reader sees that an answer came from what the ontology means by a word
and not only from how it is spelled. Nothing is inferred into the store: the rewriting
returns stored rows, and a row that is not stored is not an answer.

## 5. The operator language

| Operator | What it does | What it keeps |
|---|---|---|
| `resolve` | The nodes of a type whose text uses the given terms | The nodes |
| `traverse` | Where one relation leads from everything carried | The nodes and the links crossed |
| `filter` | What carried satisfies a condition on a field, or is of a type | The subset |
| `join` | A traversal used to intersect | The nodes and links |
| `aggregate` | How many things are carried | The count, over the whole set |
| `compare` | The carried things grouped by what a field says | The groups |
| `oppose` | A traversal along a relation that means disagreement | The nodes and links |

Every operator produces an `Executed` carrying what it selected, the links it crossed,
and — when it selected nothing — **why**.

## 6. The three rules

### 6.1 A plan is type-checked before it runs

Every operator's arguments are checked against the loaded ontology: a relation it does
not declare, a class it does not have, an operator missing what it needs. All of them, at
once, before anything executes — so the failure names the whole plan rather than the step
that happened to run first.

This is the defence against a planner, person or model, **replacing an unknown relation
with a similar-looking word**. A plan naming `corroborates` where the ontology
declares `supports` does not run and does not produce a plausible answer built on a relation
nobody asserted. `test_a_relation_the_pack_does_not_declare_stops_the_plan_before_it_runs`
is that case.

### 6.2 An operator with no data says so, and the plan continues

A `resolve` that matched nothing hands the next operator an empty set with a reason, and
the reason travels to the end.

- A plan that **raised** would tell you it failed.
- A plan that **carried on silently** would tell you the answer is empty.

Neither says *which step emptied it*, which is the only useful thing. `Trace.emptied_at`
is that answer.

### 6.3 An aggregate counts the whole selected set

Not the top few, not what fitted in a budget. A question of the form *"how many"* is a
question about a set, and answering it from a ranked sample is answering a different
question. Where a budget did bind, `Trace.partial` says so and the step records
`more than the budget allows`.

## 7. A plan, executed

The manifest's plan:

```yaml
- {op: resolve, type: StudyResult}
- {op: filter, field: value}          # only results that recorded one
- {op: aggregate}                     # over the whole set, not a sample
- {op: traverse, predicate: observed_under}
- {op: compare, field: conditions}    # like beside like
```

and the trace it leaves:

```
resolve(type='StudyResult')              → 2 nodes
    rewritten: q(?x) :- ConditionedResult(?x); q(?x) :- NegativeResult(?x);
               q(?x) :- PositiveResult(?x); q(?x) :- RecomputableResult(?x);
               q(?x) :- StudyResult(?x); q(?x) :- computed_from_data(?x, ?_1) …
filter(field='value')                    → 2 nodes
aggregate()                              → count 2
traverse(predicate='observed_under')     → 2 nodes, 2 witness links
    rewritten: observed_under(?x, ?y); obtained_under(?x, ?y)
compare(field='conditions')              → groups: {'u1': 1, 'u2': 1}
```

The package is then built from what the last operator selected, with every node's reason
naming the operator that chose it, and the shared closure pulling in the objections.

## 8. Evolution

A new question needs a distinction the data does not carry — say, the phase of an
experiment. The plan fails to type-check or the `filter` empties, and the trace says
which. Three possibilities, in the order to check them:

1. The concept is in the ontology and the **record** does not fill it → re-extraction.
2. The concept is in an imported vocabulary and not in the profile → a mapping.
3. The concept does not exist anywhere → an ontology extension, through the ordinary
   proposal gate.

A new release re-runs the saved plans and compares the witness sets, which is the
regression test a plan language makes possible.

## 9. Competency questions

| Question | The plan |
|---|---|
| Which results under which conditions? | `resolve → filter → traverse → compare` |
| Why was this excluded? | The `Executed` of the step that dropped it, with its reason |
| How many, over everything? | `aggregate`, over the whole selected set |

## 10. Risks and acceptance

- **A plausible wrong plan.** The type check catches a plan naming nothing real; it
  cannot catch a well-typed plan asking the wrong question. That is why every step keeps
  its witnesses: checking the final text is not checking the plan, and the witnesses are
  what makes per-operator review possible.
- **The language is small**, deliberately, and a question it cannot express is a finding
  about the question rather than a reason to add an escape hatch.
- **Read-only, structurally.** No operator can write, so a plan cannot modify what it is
  answering from.

Acceptance: a plan naming a relation the ontology does not declare must not run, and a plan
that empties must name the step that emptied it. Both are tested.

## 11. Running it

```bash
atlas run architectures/a20.yaml corpus/*.pdf --store store/
atlas ask architectures/a20.yaml "which results under which conditions?" --store store/
```

A model that writes plans substitutes for the `plan` option; the type check is what makes
accepting its output safe rather than hopeful, and is the reason the seam is there.

## 12. Implementation

| Part | Where |
|---|---|
| The language | `atlas/steps/plan.py` (`Operator`, `Name`) |
| The check | `atlas/steps/plan.py` (`check`) |
| The interpreter and its trace | `atlas/steps/plan.py` (`run`, `Executed`, `Trace`) |
| The rewriting | `atlas/reason/ql.py` (`rewrite`, `directed`, `to_sql`); `atlas/steps/query.py` (`answer`) |
| Manifest | `architectures/a20.yaml` |
| Tests | `tests/test_plan.py`, `tests/test_ql.py` |
