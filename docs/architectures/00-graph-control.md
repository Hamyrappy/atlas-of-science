# Architecture 0 — Graph control

| | |
|---|---|
| **Id** | `a00` |
| **Manifest** | [`architectures/a00.yaml`](../../architectures/a00.yaml) |
| **Family** | Typed traversal |
| **Optimises** | Being comparable with the others, not being good |
| **Score** | relevance 40, novelty 15, prospect 30, **total 31** — an engineering judgement, not a measurement |

## 1. What it is for

This is the control. Sources are parsed, marked up against a fixed profile, related to
each other, stored, and answered from by a bounded typed walk. There is no argument
layer: nothing records who claims a thing, what the claim rests on, what kind of ground
that is, under which conditions it holds, or which computation produced the number.

It exists so that the other architectures can be measured. "The argument layer helped"
is a claim, and a claim needs a control that shares the parser, the extractor, the
binder, the store and the walk, so that the one thing under test is the one thing that
differs. Running architecture 5 against a text-only baseline would measure the graph;
running it against this measures the process layer.

## 2. What it is not

It is not a recommended way to build an Atlas, and it is not a text baseline either.
There is no pure vector or BM25 route here — ranking finds seeds and the answer is
still built from a walk, because a control that changed two things at once would be
useless for the comparison it exists to make.

It cannot answer, and is not expected to answer:

- who disagrees with a result, and on what basis;
- under which conditions a result was obtained, and whether two results are comparable;
- what would have to be rechecked if a dataset were retracted or a script found faulty;
- which of two mentions of the same word are the same thing.

A re-extraction over this store lands on top of whatever was there, because there is no
judgement recorded for it to land under. That is not a defect of the implementation —
the append-only store still supersedes correctly — it is the absence of anything worth
recording a judgement about.

## 3. The five questions

| | |
|---|---|
| **Schema** | [`ontologies/scierc.ttl`](../../ontologies/scierc.ttl), under `profile: RDFS`: six mention classes, seven relations. A local, versioned profile of the SciERC annotation scheme, with `dct:source` on every term and local identities of our own — the scheme publishes no OWL IRIs and this ontology does not invent any. Class hierarchy and relation signatures only; the disjointness of the six labels is in `scierc_rl`, which the control does not load. |
| **Reasoner** | RDFS entailment (`entail: {engine: rdfs}`) over the stored graph before the walk: the classes the relations' domains and ranges imply, each with its rule and its link. SHACL (`shacl_validate`) checks each record in closed world before it is asserted. |
| **Data** | Whatever store the manifest names. Nodes and links, each bound to a verbatim span of the source, in the append-only assertion log; the inverted index beside it. |
| **Components and reuse** | The SciERC scheme (labels, distinctions, relation set), the library's PDF reader, its quote binder, its inverted index and its walk. |
| **Evolution** | Editing the ontology and running again. There is no candidate pool, no promotion gate and no evidence for a change: a concept the corpus keeps using that the profile has no word for is simply not marked up. |

## 4. The ontology and the engine

The control reasons as little as a graph can and still be reasoning: **RDFS**, four rules of
the OWL 2 RL table (`prp-dom`, `prp-rng`, `prp-spo1`, `cax-sco`) run by `atlas/reason/rl.py`.
A mention recorded as the subject of `used_for` is a `Method` by the domain of `used_for`,
whatever the extractor typed it; the package says "inferred to be Method" beside it and
names the rule, and nothing is written into the store.

That is the floor every other architecture shares, which is exactly why the control has it:
a comparison against architecture 0 measures the argument layer, the induction or the
selection, not whether an engine ran at all. It deliberately stops there — no disjointness,
so two labels on one mention are not a clash here; no transitivity; no chains.

`shacl_validate` runs before `assert` against the shapes the ontology implies: each class
closed over its own fields, every node on a span, and each relation's domain and range as a
closed-world class check. A relation whose subject is not recorded as a `Method` is refused
before it is written — the relation, not the mention, since the mention may be exactly what
it says it is.

## 5. Pipeline

### 5.1 Build

```
ingest_pdf → extract_llm → relocate → validate → relate_llm → relate → shacl_validate
           → assert → index_nodes
```

1. **`ingest_pdf`** reads each PDF into a `Source` whose segments are pages. The text
   layer is frozen here and is the coordinate system for every span that will ever
   point into this source.
2. **`extract_llm`** asks the model, once per page, for typed statements with a
   verbatim quote each. The classes on offer are read out of the loaded ontology, so
   this step names no vocabulary.
3. **`relocate`** finds each quote in the frozen text and mints a node from the span it
   cut. A quote that cannot be located is dropped and counted — never placed
   approximately.
4. **`validate`** drops the nodes the ontology refuses and keeps the violations.
5. **`relate_llm`** asks, once per page that holds at least two nodes, which of them the
   page relates, offering the nodes under the reference an answer would cite them by
   and the relations the ontology declares.
6. **`relate`** places each claimed relation's quote and mints a `Link` — but only if
   the ontology allows that relation between those two classes. A forbidden pairing is
   reported as a violation with its case, not counted away.
7. **`shacl_validate`** checks the record against the shapes in closed world and
   removes what a violation refuses, with the shape's message.
8. **`assert`** writes every node and link into the store as one assertion each,
   attributed to the run.
9. **`index_nodes`** builds the inverted index beside the store.

### 5.2 Ask

```
index_nodes → retrieve → entail{rdfs} → graph_expand_entailed → graph_answer
```

1. **`retrieve`** ranks nodes against the question by distinct-term overlap normalised
   by node length. This finds seeds and nothing more.
2. **`entail`** with `engine: rdfs` types what the relation signatures imply, each
   typing with its rule and premise.
3. **`graph_expand_entailed`** walks out from those seeds — two hops, at most forty
   nodes, every relation the ontology declares — and returns a `Bundle` whose reasons
   say what each node was inferred to be.
4. **`graph_answer`** shows the model the entries, the relations in the direction they
   were asserted, and the positions, and keeps only the lines that cite a reference
   that was in front of it. With no `supports`/`opposes` configured, the positions
   section says so honestly: *none of the walked relations carries a position*. That
   sentence is the whole point of the control.

## 6. What is stored

A node per mention, typed by one of the six labels, carrying its fields and the span it
was cut from. A link per relation, typed by one of the seven predicates, carrying the
span of the text that said so and a content-hash id over what it relates and what it
stands on, so two runs that find the same relation on the same evidence write one link.

Nothing else. In particular there is no object for a position, a line of argument, a
result, a condition or a computation — the five that `ontologies/science_core.ttl` adds
and that every other architecture is built on.

## 7. Graph retrieval, exactly

```
question
  → tokenise, overlap against the inverted index, rank by overlap / sqrt(length)
  → take the top 8 node ids as roots
  → RDFS closure: classes by domain, range, sub-class, sub-relation, each with its rule
  → Adjacency over every link the store projects
  → breadth-first reach to depth 2, budget 40 nodes, both directions
  → resolve the reached ids through the store (superseded nodes drop out here)
  → Bundle{roots, nodes, links, walks, supporting: (), opposing: (), partial}
  → prompt: entries, relations (with direction), positions
  → keep only lines citing a reference that was shown
```

Two properties are inherited from the shared machinery and hold here as everywhere:
the walk is deterministic (neighbours in link-id order, which is a content hash), and a
budget that ran out is reported as `partial` rather than filled in.

The package can come back **ungrounded** — no link touched any seed — and then no model
is called at all and the run reports the gap. On a corpus whose relations have not been
extracted yet, this is the common outcome, and it is the correct one.

## 8. Evolution

There is none in the sense the other architectures mean it. The profile is fixed: it
changes when somebody edits `ontologies/scierc.ttl`, which changes `Schema.version` and
therefore the `schema_version` every future object names. Objects already written keep
naming the version they were written under and stay interpretable, because the store
keeps the schema alongside the assertions.

What is missing, deliberately, is everything that would make a change *evidenced*: no
pool of unknown concepts, no count of independent source families, no definition, no
reuse check against an external vocabulary, no promotion gate, no regression over
earlier competency questions. Architecture 4 is that, and comparing the two on one
corpus is how you find out what it bought.

## 9. Competency questions

| Question | What the walk joins | What it cannot say |
|---|---|---|
| Which methods were applied to this task? | `Method —used_for→ Task` | Whether anybody disputes it |
| Which measures was this method evaluated by? | `Method —evaluate_for→ Metric` | On which data, under which protocol |
| Which terms does this corpus use for the same thing? | `OtherScientificTerm —hyponym_of→ …` | Whether they are the same thing |

## 10. Risks and acceptance

- **The relation set is thin.** Seven predicates over six types leave most of a paper
  unsaid, and `relate` will refuse a great deal. That is visible in
  `relation_violations`, and reading those is the first thing to do on a new corpus.
- **`compare` is not "better than".** The scheme is explicit about this and so is the
  ontology; an answer that turns a comparison into a ranking is the failure to watch for.
- **A mention is not an entity.** Nothing here resolves coreference, so two pages that
  name one method produce two nodes. Counting them as two findings is the mistake this
  architecture makes and that architecture 4 exists to stop making.

It is accepted as a control when it runs end to end on the comparison corpus, produces
a grounded package for the comparison questions, and its answers are worse than the
other architectures' in ways that can be named. A control nobody can beat is a control
that was measuring the wrong thing.

## 11. Running it

```bash
atlas run architectures/a00.yaml corpus/*.pdf --store store/
atlas ask architectures/a00.yaml "which measures was this method evaluated by?" --store store/
```

## 12. Implementation

| Part | Where |
|---|---|
| Vocabulary | `ontologies/scierc.ttl` |
| Engine | `atlas/reason/rl.py` (the RDFS rules), `atlas/steps/entail.py`; `atlas/reason/shacl.py`, `atlas/steps/shacl_validate.py` |
| Relation extraction | `atlas/steps/relate_llm.py`, `atlas/steps/relate.py` |
| The walk | `atlas/walk.py`, `atlas/steps/graph_expand.py` |
| Answering | `atlas/steps/graph_answer.py` |
| Manifest | `architectures/a00.yaml` |
| Tests | `tests/test_relate.py`, `tests/test_rl.py`, `tests/test_shacl_validate.py`, `tests/test_graph_expand.py`, `tests/test_graph_answer.py`, `tests/test_catalogue.py` |
