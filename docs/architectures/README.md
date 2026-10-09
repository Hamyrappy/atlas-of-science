# Architectures

Fifteen ways to turn a corpus into markup you can answer scientific questions from,
each shipped as a configuration you can run, and each written up in its own
specification beside this file.

An architecture here is not a mode, a flag or a class. It is a manifest under
`architectures/`: the ontologies it loads and the OWL 2 profile they must stay within, the
chain of steps that builds the graph, the chain that answers a question over it, the
engines some of those steps run, and the options each step runs under. Nothing in
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

## What they all stand on

The same two halves, whichever architecture is chosen. The **TBox** is the OWL 2 modules a
manifest names under `schema:` -- with the profile they must stay within, which decides which
engine may reason over them -- and the SHACL shapes records are held to. The **ABox** is the
property graph the build chain writes into a store as assertions: nodes labelled with one class,
links labelled with one relation, every one of them on a verbatim span. An architecture differs
from another in which steps it runs over these, never in what they are.

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

## The ontology each one reasons with

Every architecture names its ontologies, the profile they must stay within, and runs the
engine made for that profile. Which one follows from what its questions need the ontology
to say; every specification has a section on its ontology and its engine that says why,
and the manifest's `reasoning:` line says it in a paragraph.

| Profile | Engine | Runs over | Architectures |
|---|---|---|---|
| RDFS | the four RDFS rules | the data | 0 |
| OWL 2 RL | the RL rule table, with derivations and clashes | the data | 5, 6, 7, 10, 13, 18, 19 |
| OWL 2 EL | completion-based classification | the ontology | 4, 12, 16 |
| OWL 2 QL | query rewriting, run as SQL | a query | 8, 14, 20 |
| OWL 2 DL | the tableau; RL over the data | the ontology | 15 |

Only the first two run over what was extracted, because only those cannot conclude that
something exists which nobody mentioned. A derived fact carries its derivation and the
spans of its premises, and a package says which of its relations nobody claimed.
`tests/test_catalogue.py` refuses an architecture whose engine is not complete for the
profile it names, and runs every `ask` chain end to end over a small store.

## The specifications

Each one is a standalone document that opens the same way — what it is for, what it is
not, the five questions — so two of them can be read side by side without hunting for the
part that differs. Each then has a section on its ontology and its engine, and states how
it is built, the exact
retrieval algorithm, how the schema evolves under it, the competency questions it is meant
to answer, its risks, how to run it, and which files in this repository implement it.

| # | Architecture | Optimises | Specification |
|---|---|---|---|
| 0 | Graph control | Being comparable with the others | [00-graph-control.md](00-graph-control.md) |
| 4 | Corpus induction and the science map | Finding what the vocabulary is missing | [04-corpus-induction.md](04-corpus-induction.md) |
| 5 | Experiments, conditions and reproducibility | Answering "under which conditions" | [05-process-atlas.md](05-process-atlas.md) |
| 6 | Critic, bounded repair and conflict review | The cost of a wrong record | [06-critic-pipeline.md](06-critic-pipeline.md) |
| 7 | Routed scientific GraphRAG | Not answering three questions with one retriever | [07-routed-graphrag.md](07-routed-graphrag.md) |
| 8 | Relational execution of the graph contract | Answering from a large store without reading it | [08-relational.md](08-relational.md) |
| 10 | Materialised entailment with derivation provenance | Asking what the ontology already answers | [10-materialised-entailment.md](10-materialised-entailment.md) |
| 12 | Semantic units and logic profiles | Not flattening three kinds of claim into one | [12-semantic-units.md](12-semantic-units.md) |
| 13 | Federation of registries | Not manufacturing consensus out of topology | [13-federation.md](13-federation.md) |
| 14 | Mapped graph over existing tables | Reading structured data without a round trip | [14-mapped-tables.md](14-mapped-tables.md) |
| 16 | Prize-collecting subgraph selection | A vague question, at a fixed context budget | [16-selected-subgraph.md](16-selected-subgraph.md) |
| 18 | Associative graph memory | A question with no pattern | [18-associative-memory.md](18-associative-memory.md) |
| 19 | Explanatory paths with a preserved counter-path | A compact explanation that stays honest | [19-explanatory-paths.md](19-explanatory-paths.md) |
| 20 | Answering by a plan of typed graph operators | A compound question | [20-operator-plan.md](20-operator-plan.md) |
| 15 | Expressive ontology under a formal gate | Catching a contradiction before writing under it | [15-expressive-ontology.md](15-expressive-ontology.md) |

`atlas variants` prints the same list from the manifests, which is the version that
cannot go stale.

## Scores

Every manifest carries `scores` — relevance, novelty, prospect and a weighted total.
They come from the architecture catalogue this work implements and they are an
engineering judgement, not a measurement: nothing in this repository has been run over
a corpus large enough to rank these against each other. They are carried so a list can
be ordered the way its author ordered it, and they are labelled everywhere they appear
so that nobody reads them as a benchmark.
