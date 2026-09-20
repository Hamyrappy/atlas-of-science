# Architecture 4 — Corpus induction and the science map

| | |
|---|---|
| **Id** | `a04` |
| **Manifest** | [`architectures/a04.yaml`](../../architectures/a04.yaml) |
| **Family** | Dual-level retrieval |
| **Optimises** | Finding what the vocabulary is missing, without inventing it |
| **Score** | relevance 91, novelty 92, prospect 94, **total 92** — an engineering judgement, not a measurement |

## 1. What it is for

A vocabulary written before the corpus was read is wrong about the corpus, and the
useful question is *which part* of it is wrong. This architecture imports a scientific
core up front and then lets the corpus push back: everything the pack has no word for
is kept rather than discarded, pooled by what the labels have in common, counted in
independent source families, defined, checked against what already exists, and put
through a gate. What comes out the other end is a **proposal** — a file somebody reads
— and never an edit to the vocabulary a corpus is being marked up against.

Beside it runs a second layer that answers a different question: what is discussed
together. That layer is a map, not a taxonomy, and keeping the two apart is the whole
discipline of this architecture.

## 2. What it is not

It is not "unsupervised ontology learning". Three things are deliberately absent:

- **Nothing promotes itself.** `promote` writes `proposal.yaml`; merging it into a pack
  is a person's decision, and the pack is what `Schema.version` hashes, so an unreviewed
  proposal cannot change what any object is written under.
- **A cluster is not a class.** Topics carry the kinds of their members and report
  `mixed` when there is more than one. A dense group holding a method, a task and a
  benchmark is a subject area; the architecture says so in a field rather than promoting
  it as `RetrievalThings`.
- **No embedding decides a meaning.** Grouping is term overlap (Jaccard over folded
  tokens), which is crude and says so. It does not pretend to understand either word,
  and every threshold it used is reported on the candidate.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core` (the argument: proposition, position, evidence line, result, conditions, computation) + `science_map` (topic, kept passage) + `scierc` (mention types and their relations). The first is what the corpus extends; the third is what mentions are typed by. |
| **Reasoner** | None at query time. The gate is where judgement happens, and it is mechanical: support, rounds, definition, reuse. Topic clustering is not inference and is never called that. |
| **Data** | Nodes, links and their assertions in the store; the candidate pool as `candidates.json` beside it; the proposal as `proposal.yaml`; the topic map rebuilt per run and never asserted. |
| **Components and reuse** | The imported core; the SciERC scheme for mention types; `atlas.text` for folding and terms; `atlas.walk` for the connected groups; the shared `Bundle`. |
| **Evolution** | The subject of the architecture. Pool → definition → reuse check → gate → proposal → review → pack edit → new `Schema.version`. Objects already written keep naming the version they were written under. |

## 4. Pipeline

### 4.1 Build

```
ingest_pdf → extract_llm → salience_llm → relocate → validate
           → relate_llm → relate → assert
           → induce → define_llm → promote → index_nodes
```

The order of the first two model passes matters and is not arbitrary. `extract_llm`
produces the statements; `salience_llm` **adds** to them. Running salience first would
have its output replaced by the extractor's, and running it as a filter would make its
own recall unmeasurable — which is the failure mode that matters, because a salience
pass does not fail by keeping noise. It fails by losing the negative result.

`salience_llm` reads every segment once and keeps the regions carrying one of four
configured categories — contribution, definition, limitation, negative result — as
`Passage` nodes with the category in a field. The categories are in the manifest, not in
the code: which distinctions matter belongs to the corpus. `kept` counts them per
category, and that count is the number to watch.

`induce` then pools every statement whose type the schema does not know:

- labels are grouped by term overlap above a threshold (0.6 by default, reported);
- **support counts independent source families**, not mentions — ten mentions in one
  paper are one paper, and a family is a source id or a `Source.meta` key the corpus
  knows better by (a venue, a group, a registry);
- the quotes behind the group are kept, a few per candidate;
- the closest term the loaded schema already has is attached to every candidate, with
  the overlap;
- the pool is merged with `candidates.json` beside the store, so **rounds are runs**.

`define_llm` asks for a definition in genus-and-differentia form for every candidate
that has none. Two named parts, because the reuse question is then answerable in one
reading: an empty differentia means the candidate *is* the nearest existing term. A
reply saying so pushes the candidate's similarity to certainty, and the gate refuses it
by name.

`promote` is the gate, in this order:

1. support in fewer than `min_support` independent families → refused;
2. seen in fewer than `min_rounds` rounds → refused;
3. overlap with the nearest existing term at or above `reuse` → *refused as a reuse,
   naming the term to use instead*;
4. no definition → refused.

Reuse is checked before the definition on purpose: a candidate that is the term the
schema already has does not need a definition written for it.

What passes becomes `proposal.yaml` — a pack **fragment**, with no prefixes and no
IRIs, because minting an identity is the review and a file that guessed one would have
made the review look finished.

### 4.2 Ask

```
index_nodes → topics → retrieve_dual → graph_expand → graph_answer
```

`topics` builds the map: the connected groups of the graph, each labelled from the
terms its members share and carrying the kinds of those members. Rebuilt every time,
asserted never.

`retrieve_dual` matches the question against two things at once — the nodes by their own
terms, and the topics by the terms their members share — and every hit records which
branch found it (`Hit.via`). A node reached only through a topic scores at
`weight × topic score`, below one the question actually named, which is what stops a
large topic from flooding the seeds.

## 5. The three identities

This is the part that is easiest to get wrong and the part the architecture exists to
get right.

| | What it is | Where it lives | What it is not |
|---|---|---|---|
| **Mention** | A place in a text where something is named | A `Node` with its span | Not an entity: two pages naming one method are two nodes until something says otherwise |
| **Topic** | A group of things the corpus discusses together | A `Topic`, rebuilt per run, never asserted | Not a class: `mixed` says when it holds several kinds |
| **Class** | A kind of thing | A `TypeDef` in a pack, hashed into `Schema.version` | Not something a model can create: only a reviewed proposal becomes one |

The only route from the first to the third runs through `induce` → `define_llm` →
`promote` → a person. There is no route at all from the second to the third, and that
is deliberate.

## 6. Graph retrieval, exactly

```
question
  → tokenise
  → branch A: overlap against the inverted index          → score
  → branch B: overlap against each topic's shared terms
              take the best `topics` of them
              their members score topic_score × weight
  → merge by max, order by score then id, take `limit`
  → Hit{node, score, via: "question" | "topic"}
  → graph_expand: depth 2, budget 50, supports=[supports], opposes=[disputes]
      - breadth-first reach from the hits
      - objections pulled in after the walk whatever the budget did
  → graph_answer: entries, relations with direction, the two sides named
  → keep only lines citing a reference that was shown
```

## 7. Evolution, with a worked negative case

The corpus starts using a word the pack has no room for. Round one: three papers, one
venue — `induce` pools it, `support` is 1 because the family is the venue, the gate
refuses it for thin support. Round two: two more venues — support 3, rounds 2,
`define_llm` writes "a preparation step, performed before measurement", the nearest
existing term is `Study` at 0.2 overlap, and it promotes into `proposal.yaml`.

The negative case is the one that matters. A group forms around a retrieval model, a
question-answering task and a benchmark; they co-occur constantly and `topics` puts them
in one topic. That topic is **not** a candidate class, and nothing in the pipeline can
make it one: topics and candidates are different objects reached by different steps, and
the topic reports `mixed: true` with `kinds` naming three types. The right outcome is
what the architecture does — the group stays on the map, and any class that comes out of
that area comes out of `induce` from labels the pack refused, one kind at a time.

## 8. Competency questions

| Question | What it uses | Why it is answerable here |
|---|---|---|
| Which concepts has this corpus started using that we have no word for? | `candidates` → families → quotes → nearest term | Novelty with the sources behind it and the existing term beside it |
| Is this a new topic or a new kind of thing? | `Topic.kinds`/`mixed` against the candidate pool | The two layers are separate objects, so the question has an answer |
| Which of these were already somebody else's word? | `Candidate.nearest`, `Candidate.similarity` | Reuse is reported on every candidate, promoted or refused |
| What does this corpus say for and against a claim? | `graph_expand` with supports/opposes | The imported core carries the argument |

## 9. Risks and acceptance

- **Salience loses the negative result.** The failure that matters. `kept` counts per
  category; a corpus where `negative result` is near zero is either unusually cheerful or
  the pass is broken, and only reading the segments settles it.
- **Term overlap is not meaning.** "step" and "steps" share no token and land in two
  candidates. This is documented, tested and visible; the answer is a lower threshold
  for a corpus that needs one, not a quiet stemmer.
- **Topics move as the corpus grows.** That is the map working. It becomes a problem
  only if something starts treating a topic id as an identity, which nothing does —
  topics are rebuilt and never asserted.
- **A model asked twice is not two families.** Nothing here counts extractions, only
  sources.

Acceptance: a corpus with the same classes but a different topic mix must not change the
vocabulary. Run the build over two corpora that share their types and differ in subject
emphasis; `proposal.yaml` must come out empty for the second.

## 10. Running it

```bash
atlas run architectures/a04.yaml corpus/*.pdf --store store/
atlas run architectures/a04.yaml more/*.pdf   --store store/     # round two
cat store/proposal.yaml                                          # for a person to read
atlas ask architectures/a04.yaml "what has this corpus started calling new?" --store store/
```

## 11. Implementation

| Part | Where |
|---|---|
| Vocabulary | `packs/science_core.yaml`, `packs/science_map.yaml`, `packs/scierc.yaml` |
| Salience | `atlas/steps/salience.py` |
| Pool and gate | `atlas/steps/induce.py` (`induce`, `promote`, `similarity`, `pack`) |
| Definitions | `atlas/steps/define_llm.py` |
| Map and dual search | `atlas/steps/topics.py` (`topics`, `retrieve_dual`, `Topic.mixed`) |
| Manifest | `architectures/a04.yaml` |
| Tests | `tests/test_salience.py`, `tests/test_induce.py`, `tests/test_define_llm.py`, `tests/test_topics.py` |
