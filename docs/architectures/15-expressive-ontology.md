# Architecture 15 — Expressive ontology under a formal gate

| | |
|---|---|
| **Id** | `a15` |
| **Manifest** | [`architectures/a15.yaml`](../../architectures/a15.yaml) |
| **Family** | Entailment traversal |
| **Optimises** | Catching a contradiction in the vocabulary before a corpus is written under it |
| **Score** | relevance 75, novelty 70, prospect 83, **total 77** — an engineering judgement, not a measurement |

## 1. What it is for

A pack is a set of axioms, and it can be wrong in ways no amount of good extraction will
survive: a type disjoint from its own ancestor, an inverse pair that does not mirror, a
transitive relation between two types nothing can be both of. Every node written under
such a pack is written under a contradiction, and finding out afterwards means
re-extracting the corpus.

This architecture makes the pack the thing under test. The gate runs before anything is
written, and it runs again before a question is answered, because the pack may have
changed since the corpus was built.

Choose it when the questions genuinely need definitions a lighter profile cannot express.
If architecture 10 answers the same competency questions, its lower curation cost is the
whole argument, and this architecture's lower score says so.

## 2. What it is not

**It never checks data.** CLAUDE.md's rule is kept exactly: a reasoner runs over the
schema only. Open-world inference over extracted markup would invent the missing spans
the markup layer exists to refuse — a node with no evidence, produced by the very
machinery that is supposed to reject one. Nothing in `formal_check` reads a node.

It is also not "consistency checking". Consistency of the whole ontology is nearly
worthless here, because an ontology with an impossible class is consistent as long as
nothing instantiates it. The property worth checking is **satisfiability of each class**,
which is §4.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core` + `process` + `science_map`, the largest stack this library ships, so that the gate has real axioms to check: three disjointness declarations across the BFO bridge, an inverse pair, two transitive relations, one symmetric. |
| **Reasoner** | `formal_check` over the schema at build **and** at ask; `entail` over the admitted relations for the entailment the pack licenses. Neither runs over data. |
| **Data** | Unchanged from the shared record. The gate's subject is the vocabulary. |
| **Components and reuse** | `Schema.disjoint`, `Schema.ancestry`, `Schema.inverse`, `CHARACTERISTICS`. |
| **Evolution** | A proposed axiom is run through the gate before release, and against the old closure: an axiom that changes an existing answer has to be defended, not merged. |

## 4. The gate

Four groups, named so that a budget can say which of them it skipped:

| Group | What it catches |
|---|---|
| `hierarchy` | A parent that does not exist; a cycle, which would make ancestry meaningless |
| `disjointness` | A type declared disjoint from something it descends from; a type whose ancestry holds two disjoint types; a disjointness naming nothing |
| `relations` | A domain or range naming nothing; a characteristic this library cannot execute; a transitive relation between disjoint types, which can never compose |
| `inverses` | An inverse naming nothing; an inverse pair whose domain and range do not mirror |

### 4.1 An unsatisfiable class fails, with no instance required

A pack whose `Reagent` is a subclass of `MaterialEntity` and also declared disjoint from
it is *consistent* in the trivial sense — no instance, no contradiction — and it is
broken. The first extractor that produces a `Reagent` produces a node that cannot exist.
`test_a_class_nothing_instantiates_still_fails_the_release` is that case.

### 4.2 A check that was not run is reported as not run

Where the budget stops the checking, `unchecked` names the groups that were skipped and
`Report.passed` is **false**. "Nothing was found" and "nothing was looked for" are
different answers, and a gate that conflated them would pass every pack too large to
check. This is the same discipline as a timeout on a real reasoner meaning *not
verified*, rather than *verified*.

### 4.3 Strict means it stops the run

`formal_check` is the first step of the build chain with `strict: true`, so a broken
pack raises before a single source is read. The error names up to five problems, with
kind, term and detail, and says how many more there are.

## 5. Pipeline

### 5.1 Build

```
formal_check(strict) → ingest_pdf → extract_llm → relocate → validate
                     → relate_llm → relate → assert → index_nodes
```

### 5.2 Ask

```
formal_check(strict) → index_nodes → retrieve → entail
                     → graph_expand_entailed → graph_answer → check_answer
```

The gate runs again before answering. The pack may have been edited since the corpus was
built, and answering questions under an unsatisfiable ontology is exactly as wrong as
writing under one.

The entailment available at query time is the closure of architecture 10, unrestricted
here (`entail` with no `premises`, so every relation the pack gives a characteristic).
Derived relations are marked in the package and in the prompt, so the answer distinguishes
what follows from what a source reported.

## 6. What the shipped packs actually assert

The gate is only as valuable as the axioms it checks, so the shipped vocabulary carries
real ones:

- `MaterialEntity`, `Process` and `InformationEntity` are **pairwise disjoint**. That is
  the BFO bridge as an axiom: a file of instructions is not the procedure being carried
  out, and neither is a sample.
- `Protocol`/`ProtocolStep` are information; `Experiment`/`ExecutionStep` are processes.
  The disjointness above makes "a protocol was classified as an experiment" a gate
  failure rather than a subtlety somebody has to notice.
- `part_of` is transitive, `has_part` is its inverse, `comparable_with` is symmetric,
  `narrower` is transitive.

`tests/test_formal_check.py` runs every shipped pack combination through the gate, which
is what keeps that honest as the vocabulary grows.

## 7. Evolution of an axiom

A proposed class definition conflicts with an imported one. The wrong response — and the
one worth naming because it is tempting — is to drop the inconvenient import. The right
one is to decide which of three things is true: the description was translated wrongly,
the wrong external term was chosen, or the local extension needs different modelling.

The change is then a new pack version, run through the gate, and run against the previous
closure: an axiom that changes existing answers has to be defended on those answers, not
merged because it passes.

## 8. Competency questions

| Question | What the gate and the closure give |
|---|---|
| Does membership follow from these properties? | Entailment over the pack's relation axioms |
| Which axioms make this classification impossible? | The `unsatisfiable` and `self-disjoint` problems, with terms |
| Why can these two vocabularies not be merged by this bridge? | `inverse-mismatch`, `unknown-domain`/`range` on the bridge's own relations |

## 9. Risks and acceptance

- **Curation cost.** An expressive pack is harder to write and harder to keep
  satisfiable. If no competency question distinguishes this from architecture 10, its
  lower score is justified and 10 is the right choice.
- **"Formally consistent" is not "scientifically true".** The gate says the vocabulary
  can be satisfied. It says nothing about whether the corpus was read correctly.
- **The gate is cheap here and would not be with a real reasoner.** The budget mechanism
  exists for the case where it stops being cheap, and it fails closed.

Acceptance: every shipped pack passes; a deliberately broken pack fails with the right
kind named; and a pack too large for the budget fails rather than passes. All three are
tested.

## 10. Running it

```bash
atlas run architectures/a15.yaml corpus/*.pdf --store store/
atlas ask architectures/a15.yaml "does membership follow from these properties?" --store store/
```

## 11. Implementation

| Part | Where |
|---|---|
| Axioms in a pack | `atlas/model/schema.py` (`disjoint_with`, `disjoint`, `characteristics`, `inverse_of`) |
| The gate | `atlas/steps/formal_check.py` (`inspect`, `Report`, `Problem`, `CHECKS`) |
| Entailment at query time | `atlas/steps/entail.py` |
| Manifest | `architectures/a15.yaml` |
| Tests | `tests/test_formal_check.py`, `tests/test_entail.py` |
