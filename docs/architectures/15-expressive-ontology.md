# Architecture 15 — Expressive ontology under a formal gate

| | |
|---|---|
| **Id** | `a15` |
| **Manifest** | [`architectures/a15.yaml`](../../architectures/a15.yaml) |
| **Family** | Entailment traversal |
| **Optimises** | Catching a contradiction in the vocabulary before a corpus is written under it |
| **Score** | relevance 75, novelty 70, prospect 83, **total 77** — an engineering judgement, not a measurement |

## 1. What it is for

An ontology is a set of axioms, and it can be wrong in ways no amount of good extraction
will survive: a class disjoint from its own ancestor, an inverse pair that does not mirror, a
transitive relation between two types nothing can be both of. Every node written under
such an ontology is written under a contradiction, and finding out afterwards means
re-extracting the corpus.

This architecture makes the ontology the thing under test. The gate runs before anything
is written, and it runs again before a question is answered, because the ontology may
have changed since the corpus was built.

Choose it when the questions genuinely need definitions a lighter profile cannot express.
If architecture 10 answers the same competency questions, its lower curation cost is the
whole argument, and this architecture's lower score says so.

## 2. What it is not

**It never checks data.** CLAUDE.md's rule is kept exactly: a reasoner runs over the
schema only. Open-world inference over extracted markup would invent the missing spans
the markup layer exists to refuse — a node with no evidence, produced by the very
machinery that is supposed to reject one. Nothing in `formal_check` or `classify` reads a
node.

It is also not "consistency checking". Consistency of the whole ontology is nearly
worthless here, because an ontology with an impossible class is consistent as long as
nothing instantiates it. The property worth checking is **satisfiability of each class**,
which is §4.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core_dl` (which imports `science_core_rl` and `science_core_el`) + `process_rl` + `science_map_rl`, under `profile: DL` — the largest and most expressive stack this library ships, so that the gate has real axioms to check: the BFO bridge's disjointness, inverse pairs, transitive and asymmetric relations, property chains, and the DL module's unions, qualified cardinalities and universal restrictions. |
| **Reasoner** | The OWL 2 DL tableau (`atlas/reason/tableau.py`) over the ontology, through `formal_check: {engine: dl}` at build **and** at ask and `classify: {engine: dl, strict: true}` at build. Over the data only the OWL 2 RL engine runs (`entail`), sound for DL and reporting the axioms it cannot use. |
| **Data** | Unchanged from the shared record. The gate's subject is the vocabulary. |
| **Components and reuse** | `Schema.disjoint`, `Schema.ancestry`, `Schema.inverse`, `CHARACTERISTICS`; the tableau, the EL classifier and the profile checker in `atlas/reason/`. |
| **Evolution** | A proposed axiom is run through the gate before release, and against the old closure: an axiom that changes an existing answer has to be defended, not merged. |

## 4. The gate

Six groups, named so that a budget can say which of them it skipped:

| Group | What it catches |
|---|---|
| `hierarchy` | A parent that does not exist; a cycle, which would make ancestry meaningless |
| `disjointness` | A type declared disjoint from something it descends from; a type whose ancestry holds two disjoint types; a disjointness naming nothing |
| `relations` | A domain or range naming nothing; a characteristic this library cannot execute; a transitive relation between disjoint types, which can never compose |
| `inverses` | An inverse naming nothing; an inverse pair whose domain and range do not mirror |
| `engine` | Over every axiom, by the engine named: an ontology with no model, a class that can have no member for a reason only the axioms show (§5) |
| `profile` | An axiom outside the profile the ontology is loaded under, including the OWL 2 DL global restrictions |

### 4.1 An unsatisfiable class fails, with no instance required

An ontology whose `Reagent` is a subclass of `MaterialEntity` and also declared disjoint from
it is *consistent* in the trivial sense — no instance, no contradiction — and it is
broken. The first extractor that produces a `Reagent` produces a node that cannot exist.
`test_a_class_nothing_instantiates_still_fails_the_release` is that case.

### 4.2 A check that was not run is reported as not run

Where the budget stops the checking, `unchecked` names the groups that were skipped and
`Report.passed` is **false**. "Nothing was found" and "nothing was looked for" are
different answers, and a gate that conflated them would pass every ontology too large
to check. This is the same discipline as a timeout on a real reasoner meaning *not
verified*, rather than *verified*.

### 4.3 Strict means it stops the run

`formal_check` is the first step of the build chain with `strict: true`, so a broken
ontology raises before a single source is read. The error names up to five problems, with
kind, term and detail, and says how many more there are.

## 5. The DL tableau, and why it never touches data

The gate in §4 is a set of structural checks. What makes this architecture expressive is
that the ontology says things no structural check can follow — *an evidence line supports
or disputes, and not neither* is a union on the right; *a statement states exactly one
proposition* is a qualified cardinality; *everything a line rests on is a result* is a
universal restriction — and only a reasoner for OWL 2 DL can tell whether those axioms,
together with everything else, leave a class able to have a member.

`atlas/reason/tableau.py` is that reasoner: a tableau for SRIQ — the description logic
under OWL 2 DL, without nominals and data ranges — with negation normal form, lazy
unfolding and absorption of the terminology, automata for property chains and transitive
relations, inverse relations, qualified number restrictions with the choose and merge
rules, and pairwise blocking so that it terminates on cyclic definitions. `formal_check`
with `engine: dl` asks it two things: whether the ontology has a model at all, and whether
each named class can have a member. `classify` with `engine: dl` then asks whether each
class is subsumed by each other one, which is the hierarchy a union or a universal can
imply and the EL classifier cannot see.

Two properties keep it honest. **A budget that runs out is not an answer**: the tableau
counts nodes and branches, and a class it could not decide comes back `unchecked`, which
fails the strict gate rather than passing it. **What it cannot read is named**: an axiom
with a nominal or a data range is reported as outside what was decided, never dropped
quietly.

It never runs over data. A DL reasoner over extracted markup would conclude, from *every
result was obtained under some condition*, that a condition exists that no source
mentioned — an individual with no span, produced by the machinery that exists to refuse
one. So at question time the engine is OWL 2 RL, whose rules are sound for OWL 2 DL and
never invent an individual; the DL axioms it cannot use are listed in the closure's
`ignored`, by name.

## 6. Pipeline

### 6.1 Build

```
formal_check(strict, dl) → classify(strict, dl) → ingest_pdf → extract_llm → relocate
                         → validate → relate_llm → relate → assert → index_nodes
```

### 6.2 Ask

```
formal_check(strict, dl) → index_nodes → retrieve → entail
                         → graph_expand_entailed → graph_answer → check_answer
```

The gate runs again before answering. The ontology may have been edited since the corpus was
built, and answering questions under an unsatisfiable ontology is exactly as wrong as
writing under one.

The entailment available at query time is the OWL 2 RL closure of architecture 10, over
every relation (`entail` with no `premises`), with the DL axioms it cannot use listed in
`ignored`.
Derived relations are marked in the package and in the prompt, so the answer distinguishes
what follows from what a source reported.

## 7. What the shipped ontologies actually assert

The gate is only as valuable as the axioms it checks, so the shipped vocabulary carries
real ones:

- `MaterialEntity`, `Process` and `InformationEntity` are **pairwise disjoint**. That is
  the BFO bridge as an axiom: a file of instructions is not the procedure being carried
  out, and neither is a sample.
- `Protocol`/`ProtocolStep` are information; `Experiment`/`ExecutionStep` are processes.
  The disjointness above makes "a protocol was classified as an experiment" a gate
  failure rather than a subtlety somebody has to notice.
- `part_of` is transitive, `has_part` is its inverse, `comparable_with` is symmetric,
  `narrower` is transitive; `directly_depends_on` is asymmetric under a transitive
  `depends_on`, because OWL 2 DL forbids a transitive relation that is also irreflexive.
- In the DL module: an evidence line supports or disputes (a union on the right), a
  statement states exactly one proposition (a qualified cardinality), everything a line
  rests on is a result (a universal), and the outcomes with a direction are partitioned
  into positive and negative.

`tests/test_formal_check.py` runs every shipped combination through the gate, and
`tests/test_ontologies.py` runs the tableau over every module and checks each stays inside
the profiles it declares, which is what keeps that honest as the vocabulary grows.

## 8. Evolution of an axiom

A proposed class definition conflicts with an imported one. The wrong response — and the
one worth naming because it is tempting — is to drop the inconvenient import. The right
one is to decide which of three things is true: the description was translated wrongly,
the wrong external term was chosen, or the local extension needs different modelling.

The change is then a new ontology version, run through the gate, and run against the previous
closure: an axiom that changes existing answers has to be defended on those answers, not
merged because it passes.

## 9. Competency questions

| Question | What the gate and the closure give |
|---|---|
| Does membership follow from these properties? | The DL classification (`classify`), and the RL closure over the data |
| Which axioms make this classification impossible? | The `unsatisfiable` and `self-disjoint` problems, with terms |
| Why can these two vocabularies not be merged by this bridge? | `inverse-mismatch`, `unknown-domain`/`range` on the bridge's own relations |

## 10. Risks and acceptance

- **Curation cost.** An expressive ontology is harder to write and harder to keep
  satisfiable. If no competency question distinguishes this from architecture 10, its
  lower score is justified and 10 is the right choice.
- **"Formally consistent" is not "scientifically true".** The gate says the vocabulary
  can be satisfied. It says nothing about whether the corpus was read correctly.
- **The tableau is exponential in the worst case.** On the shipped stack it decides every
  class in well under a second and classifies pairwise in a few; the budget exists for
  the ontology where that stops being true, and it fails closed.

Acceptance: every shipped ontology passes; a deliberately broken one fails with the right
kind named; one made unsatisfiable only by a union fails the DL gate and not the EL one;
and one too large for the budget fails rather than passes. All four are
tested.

## 11. Running it

```bash
atlas run architectures/a15.yaml corpus/*.pdf --store store/
atlas ask architectures/a15.yaml "does membership follow from these properties?" --store store/
```

## 12. Implementation

| Part | Where |
|---|---|
| The axioms | `ontologies/science_core_dl.ttl` and the modules it imports, read into `atlas/model/owl.py` |
| The tableau | `atlas/reason/tableau.py` (`decide`, `Verdict`); `atlas/steps/classify.py` (`by_dl`) |
| The profile | `atlas/reason/profile.py` (`outside`, `explain`) |
| The gate | `atlas/steps/formal_check.py` (`inspect`, `Report`, `Problem`, `CHECKS`) |
| Entailment at query time | `atlas/steps/entail.py` |
| Manifest | `architectures/a15.yaml` |
| Tests | `tests/test_formal_check.py`, `tests/test_tableau.py`, `tests/test_classify.py`, `tests/test_ontologies.py`, `tests/test_entail.py` |
