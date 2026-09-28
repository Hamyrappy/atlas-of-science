# Tasks

What is open in this repository, against the design it implements: *Атлас науки: 20 подробных
архитектур автоонтологии и графового RAG*, revision 3, 2026-09-19. The source is a design, not
an implementation report, and it is not in this repository; every task below cites the section
it comes from so the claim can be checked against the owner's copy.

`HANDOFF.md` says where the work stands. This file says what is missing and in what order.
A task is closed by code, its tests and the document that describes it, in one commit — the rule
in `CLAUDE.md`, *Documentation is part of the change*.

## What belongs here and what does not

This is the library. A task lands here when it is a **mechanism**: a step, a model, an engine, an
ontology module, a contract every architecture shares. It lands on the platform
(`science-graph`) when it is persistence, an HTTP surface, a queue, a screen, or the vocabulary
of one customer's corpus. Where a task needs both, the line is stated in the task.

Two consequences worth stating once, because they decide the shape of most of what follows:

* **A pool that outlives a run is a file beside a store here, and a table there.** `induce`
  already merges its pool with `candidates.json`, which is what makes `min_rounds` mean
  anything. The registry below keeps that shape — a document the library reads and writes —
  and the platform is free to hold the same document in a row.
* **Nothing promotes itself.** Every task that widens what the library may propose leaves the
  decision where `promote` leaves it now: a module a person reads. A task that would let a run
  edit the ontology it is writing under is not on this list and will not be.

## The gap in one paragraph

Section 2.1 of the source makes a nanopublication the obligatory unit of every solution 1–20,
and section 2.10 makes ontology evolution a contract of all of them, with solution 0 the control
that is exempt from both. This library has neither as a shared contract: the container does not
exist at all, and evolution is a mechanism of architecture 4 (`induce` → `define_llm` →
`promote`) plus formal gates at 10, 12 and 15. Eleven of the fifteen architectures ship with a
vocabulary that cannot change and a record that cannot be published. The `S` tasks are those two
contracts; the `A` tasks are what each architecture then owes on top of them.

---

## S. The shared contracts

Every architecture except 0 depends on these, so they come before every `A` task. Within the
group the order is the source's own (§7.6): the five-component profile, then the container, then
the registry, then the gate, then the release, then the controller.

### [ ] S1. The five-component profile, completed and bridged

**Source** §2.2, §2.3, §2.6. **Gap** `ontologies/science_core.ttl` reuses SEPIO, ECO, EVI and
SIO IRIs and carries the argument layer, but the profile the source fixes is larger and more
exact: Proposition with a stable content identity separate from Statement (SPO and the
qualifiers live in the Proposition, and Statement keeps no competing copy); StudyResult,
DataItem and DataSet as the bearers of a number, its unit and its conditions, so that a
measured value is never the same field as a position's strength; Contribution and
RecordMetadata; the ECO assertion-method branch (`ECO_0000217`, `ECO_0000203`, `ECO_0000218`)
kept apart from the evidence-type branch, because how a record was made is not what the science
rests on; and EVI's two different computations — the one that produced the scientific result and
the one that extracted the record — never conflated.

**Where** `ontologies/science_core*.ttl` and a bridge module; `ontologies/fields.ttl` for the
value/unit fields; `ontologies/shapes/` for the closed-world requirements; `docs/ontology.md`.

**Done when** a node carrying a number carries its unit and its conditions as declared fields;
an extraction that put a support strength in a measurement field is refused by a shape; the
assertion-method and evidence-type branches are separately queryable; `tests/test_ontologies.py`
holds the enlarged modules to their profiles and the tableau finds every class satisfiable.

**Not this task** the LinkML edition. The source (§2.2) warns that SEPIO OWL and SEPIO LinkML
are not interchangeable by name; where an axiom is needed it comes from a bridge module that
was checked, and that check is part of this task's evidence.

### [ ] S2. The nanopublication container: four graphs, TriG bytes, a verifiable identity

**Source** §2.1, §2.9. **Gap** nothing in this repository knows the word. What exists is the
raw material: `Assertion` carries the agent, the time, the target and what it supersedes;
`Node` and `Link` carry their spans; `atlas/ontology/abox.py` already writes nodes, links and
spans as RDF with a reified `atlas:Link` and W3C Web Annotation selectors. What is missing is
the container: Head, Assertion, Provenance and Publication info as four named graphs, canonical
TriG bytes, and an identity computed over the RDF dataset rather than over a JSON serialisation.

**Where** a new module beside `abox.py` — `atlas/ontology/nanopub.py` — and one step,
`publish`, that takes what a store holds and produces the containers. `docs/ontology.md` gets
the section; `docs/architecture.md` gets the container in the provenance chain.

**Done when** a stored assertion round-trips: container → parse → the same node, link, spans,
schema version, agent and supersede edge; the bytes are stable across two runs over the same
store; the identity refuses a tampered graph; a container whose assertion graph names a class
the schema does not declare is refused before it is written. Publication info carries the
extractor, the schema version and the prompt version, which are what §2.1 names.

**Not this task** a triple store. RDF stays a projection (`CLAUDE.md`, *the ABox is never
stored as RDF*); the container is bytes, and the platform decides where the bytes live.

### [ ] S3. A candidate registry that outlives a run, with states

**Source** §3.3, §7.3. **Gap** `Candidate` (`atlas/steps/induce.py`) carries term, variants,
families, examples, definition, nearest term, similarity and rounds. The source requires more of
it, and requires it to have a life: representatives **and counterexamples**, the distribution of
predicate roles the term appeared in, the external nearest term as distinct from the local one,
the competency question that needs it, and a state — `observed → candidate → validated →
released → superseded/deprecated` — that moves by a recorded decision and never backwards
silently.

**Where** `atlas/steps/induce.py` (`Candidate`, the pool merge), and the pool document itself,
whose shape becomes a contract rather than an implementation detail of one step.

**Done when** a counterexample recorded in round one is still attached in round three; a term
refused by the gate is `candidate`, not absent; a promoted term that a later round contradicts
moves to `superseded` with the reason and the round; the history is monotone — nothing is
rewritten — and `rounds` is derived from it rather than stored beside it.

**Line with the platform** the document is the library's; holding it in a table is the
platform's. Neither may invent a state the other does not know.

### [ ] S4. The full promotion gate

**Source** §3.3, §7.3. **Gap** `promote` checks four things: support in independent families,
rounds, reuse against the loaded schema, and the presence of a definition. The source's gate is
eight: those four plus **sufficiency of context**, **shapes**, **the reasoner** and **CQ
regression** — and adds a separate, explicitly expert-confirmed route for a rare term a
competency question actually needs, which the support threshold would otherwise refuse forever.

**Where** `atlas/steps/induce.py` (`promote`); the CQ regression needs a question set in the
state, which is `S7`; the shapes and reasoner checks reuse `atlas/reason/shacl.py` and the
existing `module`/`check` pair, which already loads a proposal with the run's ontology.

**Done when** a proposal that would break an existing competency question is refused naming the
question; a proposal whose class no shape can validate is refused naming the shape; the expert
route is a distinct outcome in `refused`, not a lower threshold; every refusal still carries its
reason in words, as it does now.

### [ ] S5. A release: one object, locked

**Source** §3.3, §7.3. **Gap** a schema here is a set of files and a hash of their bytes. A
release in the source is one object that locks the TBox, the RBox, the shapes, `imports.lock`,
the extraction schema, the mappings, the competency-question queries and a migration plan, so
that "the ontology changed" is a thing with edges rather than a diff.

**Where** `atlas/model/schema.py` gains the release; `atlas/ontology/__init__.py` loads and
writes one; `docs/ontology.md` states what a version is now.

**Done when** a run records the release it ran under, not only the schema hash; two releases
differing only in shapes are two releases; an object written under an older release stays
interpretable, which is invariant 3 and is already true of `schema_version` — the task is to
keep it true of the larger object.

### [ ] S6. The incremental controller: dependencies, triggers, selective rebuild

**Source** §7.3, §2.10. **Gap** nothing recomputes. A new release changes what future runs are
written under and touches nothing already stored. The source requires the six levels of §7.3 —
ABox, TBox, RBox, shapes, mappings, extractor/retriever — each with what it forces to be
recomputed, and a dependency index that decides which records are revalidated, reclassified,
re-extracted and reindexed. Where the impact cannot be bounded, a whole module is rebuilt, and
that is a reported decision rather than a silent one.

**Where** `atlas/steps/lineage.py` already walks what a cause affects and reports
`lineage_partial`, which is the honest half of this; the task is the other half — what a release
affects — plus a step that turns an affected set into work.

**Done when** adding a subclass axiom names the stored nodes whose classification changes;
withdrawing a premise removes the derivations that stood only on it and keeps those with another
independent proof (`A10`); a rebuild that could not be bounded says so, rather than reporting a
small affected set it could not justify.

### [ ] S7. Proposal inputs other than the quarantine

**Source** §2.10. **Gap** `induce` reads one input: statements whose type the schema does not
know. The source's table has six, and four of them have no path here at all — a **competency
question that cannot be expressed**, a **repeated critic finding**, a **correct counterexample
to a universal axiom**, and an **external release**. Each proposes a different thing: a
qualifier and its shape, a bridge or an extraction rule, a split of an overloaded class, a
mapping.

**Where** new steps under `atlas/steps/`, one per input, all producing the same candidates the
registry of `S3` holds; `docs/ontology.md` gains the table.

**Done when** a question set that names a relation the ontology lacks produces a candidate
naming the question; a critic finding cluster produces a candidate only when the cause is the
schema and not the prompt (`A06`); a counterexample to a universal produces a proposal to split
or weaken the axiom and never a proposal to delete the counterexample.

### [ ] S8. Reuse against external catalogues

**Source** §3.3. **Gap** `similarity` in `induce.py` compares a candidate against the terms of
the **loaded** schema. The source requires the reuse check to reach catalogues that are not
loaded, through retrieval over their definitions, and then to verify the match by definition and
by logical position — and it forbids cosine similarity or a model's opinion from settling
`owl:sameAs` on their own.

**Where** `atlas/steps/induce.py` for the check; the catalogue itself is data, and reaching it
must not put the network inside a step — a catalogue is loaded like an ontology is loaded.

**Done when** a candidate that is a published term is refused as a reuse naming that term's IRI;
a match the definitions do not support is reported as a candidate mapping for review and never
as an equivalence; the test suite still makes no network call.

### [ ] S9. A second induction method, compared

**Source** §3.3, §4 (solution 4). **Gap** grouping is term overlap, which the specification
documents as crude and which is one method. The source names two and requires them **compared**
rather than blended: role-aware clustering over embeddings, and AutoSchemaKG-style
conceptualisation where a model proposes the covering concept and the definition is then
canonicalised.

**Where** a step of its own beside `induce`, reusing `Candidate` and the gate; the seam is the
step registry, as it is for retrieval (`CLAUDE.md`, *Steps not yet written*).

**Done when** both run over the same frozen pool and their candidate sets are reported side by
side with what each found that the other did not; neither is the default; a UMAP coordinate is
nowhere in a candidate's identity.

---

## A. What each architecture owes

Ordered as the source orders them. Each task is the mechanism that architecture's own
*Эволюция* section requires and this repository does not have. Every one of them depends on
`S3`–`S6`; where it depends on more, the task says so.

### [ ] A00. Keep 0 a control, and prove it

**Source** *Решение 0.* The control is the one architecture the source exempts: manual schema
replacement, no evidential promotion, and it is explicitly outside the twenty targets. Nothing
is to be added here. What is missing is the proof that it still works as a control after `S5`:
a release replaced by hand must leave the earlier run reproducible and its nodes interpretable.

**Done when** a test replaces the schema under a stored graph and the old run still answers its
question with its original classification; `docs/architectures/00-graph-control.md` says that
this is the property being controlled for.

### [ ] A04. Both induction methods, three identities, and rounds that persist

**Source** *Решение 4.* **Gap** this is the architecture closest to the source and still short
of it. The three identities are right — `mention_id`, `topic_id`, `class_iri` are separate
objects and there is no route from topic to class, which §"Детализация трёх слоёв" demands. What
is missing: the second induction method (`S9`) compared against the first; the candidate
accumulator of §3.3 with counterexamples and predicate-role distributions (`S3`); **fast
assignment** — a new mention placed under a promoted class by meaning *and* role, with the
ambiguous case returned to quarantine rather than guessed; and the science map's growth
reported with its denominator and snapshot coverage rather than as a count.

**Done when** the acceptance test of the source passes: a corpus with the same classes and a
different topic mix leaves `proposal.ttl` empty; a mixed Method/Task/Material group stays a
topic under every method; a promoted term keeps its IRI and definition across a release, and
what the old class meant is not rewritten.

### [ ] A05. Process gaps propose, and a computation's error revises

**Source** *Решение 5.* **Gap** `align` compares plan against run and `compare` compares results
under their conditions, which is the answering half. The evolution half is absent: a failed
reproduction must first compare protocols and actual steps, and only then — when the difference
is real — propose a **slot or a shape for the missing condition**, or the import of a
preparation-process type. Lowering a consensus score instead is the failure mode the section
names. Separately, a code error must revise the EVI subgraph and the results that depend on it
(`S6`), and a causal explanation must stay an attributed Statement and never become an axiom.

**Done when** two reports with similar text and different conditions stay unmerged; a missing
condition surfaces as a qualifier proposal naming the reproduction that exposed it; changing a
software version names the dependent results and leaves the independent ones alone.

### [ ] A06. Critic findings cluster, and only a schema cause proposes

**Source** *Решение 6.* **Gap** `critique` and `repair_llm` fix records. Nothing groups repeated
findings or asks *why* they repeat. The source requires a separate reviewer that clusters
identical errors and distinguishes three causes — the extractor prompt, insufficient grounding,
and a genuine schema gap — and lets **only the third** reach `S7`. It also requires the proposal
to be regressed over both the previously wrong and the previously correct cases, and it notes
that an imported BFO process / IAO information-content distinction often covers the gap, so a
bridge is proposed before two local classes are.

**Done when** ten records confusing a method with its execution produce one cluster with a
named cause; a prompt cause produces no schema proposal; an accepted proposal keeps every
previously correct record correct, measured on those records.

### [ ] A07. Derived layers are invalidated by their dependencies

**Source** *Решение 7.* **Gap** `topics` and `communities` are rebuilt per question and never
asserted, which is honest and is why nothing goes stale — and also why nothing is *invalidated*,
which is what the section requires once reports exist: withdrawing a study invalidates not only
its statement but every report that used it, and where the lost support is a large share, the
survey projection drops the thesis until it is rebuilt. Schema and reports are released
together, so a snapshot is never half old.

**Done when** changing a member claim prevents the previous report from appearing in the new
snapshot; a report is never counted as independent support (it is derived information with its
own generation provenance); each of the three routes has a witness graph of its own.

### [ ] A08. The record's form migrates, and the round trip proves it

**Source** *Решение 8.* **Gap** the QL chain answers over SQLite and Postgres. What the section
adds is evolution of the **form**: a profile that starts distinguishing a dataset's version from
its logical identity gains a version node and a relation — never a string suffix on a name —
and old records without an exact version stay `unknown` until a targeted extraction finds a
ground for one, with "compare on the same version" excluding them visibly. It also requires the
relational execution to be recoverable to RDF, which is `S2`.

**Done when** a migration adds the version relation, compatible views answer the old queries,
`unknown` is distinguishable from "not compared", and the container round-trips through the
relational form without losing a qualifier, a context or an IRI.

### [ ] A10. Consequences are persisted, and a retraction is exact

**Source** *Решение 10.* **Gap** `entail` derives with derivations and clashes, per question,
and stores nothing — which the specification defends and the source contradicts for this
architecture specifically: it requires a materialised layer, and with it a **dependency
recorder** that, when a premise is withdrawn, finds the affected derivations rather than
deleting one edge and orphaning its consequences, and that records for each conclusion whether
it also follows from an independent set of premises.

**Done when** withdrawing a premise removes exactly the conclusions that stood only on it;
a conclusion with a second proof survives and says so; the old closure stays reproducible; an
axiom release produces an old/new entailment diff. This is the one architecture whose task
argues with its own specification — settle that in `docs/architectures/10-*.md` in the same
commit, with the reason.

### [ ] A12. Templates are versioned, and a new form proposes one

**Source** *Решение 12.* **Gap** `compile_units` rules on a form and translates the exact ones,
which is the whole of §"Детализация". The evolution half is absent: a corpus that starts saying
"the method applies only if…" is a **conditional template** the profile lacks, and the section
is explicit that the answer is usually to extend the expression and its shape rather than to
mint a class per grammatical construction. Templates therefore need versions, and a release
must reinterpret the affected units **selectively**, keeping the old interpretation readable.

**Done when** positive, negated, qualified and quantified pairs stay distinguishable across a
template release; an unsupported form is untranslated rather than partially translated into
something stronger; a template update rewrites no unaffected unit; the adversarial cases on
negation scope and conditions are in the suite.

### [ ] A13. An external release is admitted, not applied

**Source** *Решение 13.* **Gap** `federate` reads registries and `count_independence` refuses to
count a duplicate twice. What is missing is the ontology half: an external module deprecating a
class must produce an **ontology-update proposal** that is checked against the definitions, the
competency questions and the mappings — never a rename of the IRI across stored records — and a
class split must be resolved from the grounds in the original statements, with the undecidable
records left on the old release and visibly awaiting handling.

**Done when** a deprecation produces a proposal and changes nothing until it is accepted; a
split leaves ambiguous records on the old release rather than guessing by label; an unknown
external module waits for a mapping instead of being partially read.

### [ ] A14. A mapping revision is a semantic decision

**Source** *Решение 14.* **Gap** `map_rows` maps rows with a mapping written in a configuration.
The source's case is the one that matters: a renamed column with a changed unit still returns
numbers, and syntactically repaired SQL hides that the meaning moved. It requires the controller
to compare schema metadata against the unit assertions, raise a mapping revision, and check the
old fixtures; a convertible unit becomes an explicit transformation with its parameters, and a
different kind of measurement becomes an imported term.

**Done when** a changed unit fails a fixture rather than passing quietly; a conversion is
recorded as an action with parameters and not folded into the value; old snapshots keep their
original values.

### [ ] A15. An axiom is proposed, explained and released

**Source** *Решение 15.* **Gap** the gate runs — `formal_check` and `classify` with the tableau,
before the build and before the answer, and `test_a_class_nothing_instantiates_still_fails_the_release`
is the right test. What is missing is everything after the refusal: the source requires a
**ChangeSet**, a diff showing which entailments and which satisfiabilities changed, targeted ABox
tests over known instances and negative examples, and an explicit prohibition on the obvious
escape — a model must not satisfy the reasoner by dropping the inconvenient import.

**Done when** a proposed axiom that conflicts with the imported upper layer is refused with the
conflict set; the refusal cannot be cleared by removing an import (the imports are the release's,
per `S5`); the diff is part of what a reviewer is handed; a timeout reports *unchecked* and not
*passed*, which `Report.passed` already does.

### [ ] A16. A TBox that grew is an evaluation, not an assumption

**Source** *Решение 16.* **Gap** `select_subgraph` is greedy prize-collecting growth, and the
specification says so rather than claiming a learned selector — which is the honest reduction.
The source's evolution requirement stands regardless of whether the selector is ever trained: a
new type must enter the graph through a mapping and a textual definition, and the selector's
ability to handle it is **evaluated, never assumed** — frozen selector on the new questions
first, and a fall back to the unlearned control when recall drops. The fall back is between graph
methods and never to text retrieval.

**Done when** a release that adds a type produces a held-out evaluation on the new questions
before the selector is trusted with it; the control is the comparison; the graph version and any
weights are identities distinct from the ontology version.

### [ ] A18. Admission to diffusion is its own policy

**Source** *Решение 18.* **Gap** `diffuse` runs personalised PageRank over what the store holds.
The section requires the projection to be a **policy**: a released relation is not automatically
admitted to diffusion, because a scientifically correct but very general edge makes a hub
dominate; adding one is tested separately. It also requires that a term whose meaning differs in
a new field become a separate candidate — a shared label never merges — and that the adjacency
version, the embeddings, the relation policy and the PPR parameters be recorded apart from each
other.

**Done when** a newly released relation is admitted only by a passing test; a homonym across
two fields stays two nodes; a run can be replayed against the pinned adjacency; a high rank is
nowhere presented as support.

### [ ] A19. A missing relation proposes, and a path policy refuses a shortcut

**Source** *Решение 19.* **Gap** `select_paths` selects and keeps a counter-path. Two things the
section requires are absent: a search that keeps ending at an **absent relation** must raise a
proposal with the evidence behind it, and the new edge type enters the path templates only after
reuse check, release and a path-CQ regression — popularity of a path is never a ground for an
axiom. And the path policy must refuse a short path that is only short because it crosses
incompatible experimental contexts, even when every relation on it is correct; that counterexample
is kept as a fixture.

**Done when** a repeated dead end produces one proposal with its sources; a cross-context
shortcut is excluded with the reason and the fixture is in the suite; a released edge type
changes the templates only after its regression passes.

### [ ] A20. A new question is diagnosed before anything is changed

**Source** *Решение 20.* **Gap** `execute_plan` runs a plan written in the configuration, which
the specification calls the control, and the source agrees. What is missing is the diagnosis the
section makes the architecture's point: a question that cannot be filtered must be resolved in
order — is the property in the imported ontologies and merely unmapped (update the serving
profile), is it absent from the records (re-extract), or is the concept genuinely missing (and
only then extend the ontology). A release then **replays the saved plans** and reports whether
the witness sets and the answers moved; a plan cache is keyed by the ontology and operator
versions and never survives a release silently.

**Done when** each of the three diagnoses is reachable and distinguishable on a fixture; an
ill-typed or over-budget plan is refused before execution; a replay after a release reports the
moved witnesses; the static plan stays the control it is.

---

## Order

`S1` → `S2` → `S3` → `S4` → `S5` → `S6`, then `S7`–`S9` in any order, then the `A` tasks. This
is the source's own order (§7.6: the five components, then the container, then the accumulator
and the release cycle, then the specialised executions), and it is also the only order in which
the `A` tasks are small: nine of the fifteen are a few hundred lines once a release and a
dependency index exist, and all fifteen are unbounded before that.

`A00` can be done at any point and is worth doing early — it is a test, and it is the thing that
makes every later comparison mean something.
