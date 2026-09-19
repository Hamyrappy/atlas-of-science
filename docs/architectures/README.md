# Architectures

Fifteen ways to turn a corpus into markup you can answer scientific questions from,
each shipped as a configuration you can run, and each written up in its own
specification beside this file.

An architecture here is not a mode, a flag or a class. It is a manifest under
`architectures/`: the packs it loads, the chain of steps that builds the graph, the
chain that answers a question over it, and the options each step runs under. Nothing in
`atlas/` branches on which one is in use — by the time anything runs, there is only a
pipeline. That is what makes fifteen of them maintainable, and it is also what makes a
sixteenth cheap: a file, a specification, and whatever step it needs that does not exist
yet.

```bash
atlas variants                       # what is on offer
atlas variants a18 --json            # one of them, as an interface reads it
atlas run architectures/a18.yaml corpus/*.pdf --store store/
atlas ask architectures/a18.yaml "which results hold under both protocols?" --store store/
```

## The rule they all obey

**An answer is built from a walked graph.** Ranking finds where to start; it does not
find an answer. Every `ask` chain contains a step that produces a `bundle` — an
evidence package with the nodes it holds, the relations it walked, in the direction they
were asserted, the positions for and against, and the reason each thing is in it — and
ends in a step that answers from one. A package that walked nothing is reported as a
gap and never handed to a model. `tests/test_catalogue.py` checks this over every
manifest, which is the only way a rule stated in a document stays true.

Two consequences are worth stating because they are the ones that get quietly dropped
elsewhere:

- **An objection survives the budget.** Relations a configuration names under `opposes`
  are pulled into the package after the walk, whatever the limit did. An evidence
  package that fits its budget by losing the one study that disagrees reads like a
  consensus and is not one.
- **A partial package says so.** `Bundle.partial` is the difference between "there is
  nothing further" and "we stopped looking".

## What differs between them

They differ in three places, and the specifications are organised around which one:

| | What the architecture changes | Architectures |
|---|---|---|
| **The record** | What is stored about a claim, beyond the claim | 5, 8, 12, 13, 14 |
| **The build** | How the vocabulary and the graph come to exist | 4, 6, 10, 15 |
| **The walk** | How the evidence package is selected | 0, 7, 16, 18, 19, 20 |

They share everything else: the same metamodel, the same provenance rule, the same
append-only store, the same `Bundle` contract, the same refusal to answer from an
ungrounded package.

## The specifications

Each one is a standalone document with the same eleven sections, so two of them can be
read side by side without hunting for the part that differs. They state what the
architecture is for, what it is not, how it is built, the exact retrieval algorithm,
how the schema evolves under it, the competency questions it is meant to answer, its
risks, and which files in this repository implement it.

| # | Architecture | Optimises | Specification |
|---|---|---|---|
| 0 | Graph control | Being comparable with the others | [00-graph-control.md](00-graph-control.md) |
| 4 | Corpus induction and the science map | Finding what the vocabulary is missing | [04-corpus-induction.md](04-corpus-induction.md) |
| 5 | Experiments, conditions and reproducibility | Answering "under which conditions" | [05-process-atlas.md](05-process-atlas.md) |
| 6 | Critic, bounded repair and conflict review | The cost of a wrong record | [06-critic-pipeline.md](06-critic-pipeline.md) |
| 7 | Routed scientific GraphRAG | Not answering three questions with one retriever | [07-routed-graphrag.md](07-routed-graphrag.md) |
| 8 | Relational execution of the graph contract | Answering from a large store without reading it | [08-relational.md](08-relational.md) |

*(This table grows with each architecture; `atlas variants` is the version that cannot
go stale.)*

## Scores

Every manifest carries `scores` — relevance, novelty, prospect and a weighted total.
They come from the architecture catalogue this work implements and they are an
engineering judgement, not a measurement: nothing in this repository has been run over
a corpus large enough to rank these against each other. They are carried so a list can
be ordered the way its author ordered it, and they are labelled everywhere they appear
so that nobody reads them as a benchmark.
