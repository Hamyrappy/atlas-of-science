# Architecture 5 — Experiments, conditions and reproducibility

| | |
|---|---|
| **Id** | `a05` |
| **Manifest** | [`architectures/a05.yaml`](../../architectures/a05.yaml) |
| **Family** | Process-aware traversal |
| **Optimises** | Answering "under which conditions", and knowing what a retraction reaches |
| **Score** | relevance 92, novelty 89, prospect 95, **total 92** — an engineering judgement, not a measurement |

## 1. What it is for

Most of what makes a scientific result usable is not the number. It is the conditions it
was obtained under, whether the run followed the procedure it says it followed, whether
the effect failed to appear somewhere else, and what would have to be rechecked if the
data behind it were withdrawn. A record whose centre is a sentence about a finding
cannot hold any of that. This architecture puts the **doing of the work** at the centre
and hangs the claims off it.

Three questions become answerable, and they are the three this architecture exists for:

- *Under which conditions does this hold, and which results may be compared?*
- *Where does the run depart from the procedure?*
- *Which of our conclusions rest on this dataset?*

## 2. What it is not

It does not run anything, reconstruct anything or fill anything in. A paper that does
not report a condition leaves that condition **unknown**, and unknown is not equal: the
comparison says `insufficient` and names the condition it is missing. On most corpora
that is a large fraction of the results, and the architecture is working correctly when
it says so. A version of this that guessed the missing conditions would produce a much
better-looking table and would be worthless.

It also does not treat a protocol and a run of it as one thing. `ontologies/process.ttl`
declares `Protocol`/`ProtocolStep` as information and `Experiment`/`ExecutionStep` as
occurrents, and `science_core` declares those two disjoint, so "a file of instructions
was classified as a performed experiment" is a clash the RL engine reports with both
premises rather than a subtlety somebody has to notice.

## 3. The five questions

| | |
|---|---|
| **Schema** | `process_rl`, which imports `process` and `science_core_rl` and through them the base `science_core`, under `profile: RL`, with the shapes `science_core` and `process`. REPRODUCE-ME identities from the archived snapshot the catalogue cites; OBI, BFO, IAO and EVI identities from their own publications. |
| **Reasoner** | OWL 2 RL over the data (`entail`), in the build chain before `align` and in the ask chain before the walk: the property chains that carry an experiment's conditions and plan to its results and runs, with their derivations. SHACL (`shacl_validate`) before `assert`. What `align`, `compare` and `lineage` then compute is mechanical. |
| **Data** | Nodes, links and assertions in the store; comparisons and closures computed per question and never asserted. |
| **Components and reuse** | REPRODUCE-ME (archived snapshot), OBI, IAO, SIO, EVI; `atlas.walk` for the closure; `similarity` from the induction module for the shallow step matcher. |
| **Evolution** | A failed reproduction does not lower a score. It produces a comparison naming the condition that differs, which is a candidate for a new qualifier in the profile — and a proposal, reviewed, like any other schema change. |

## 4. The ontology and the engine

The questions this architecture exists for — *under which conditions*, *where did the run
depart from the plan* — are about relations nobody states directly. A paper says the
experiment ran at 20 °C and that the experiment yielded a result; it rarely says the
result was obtained at 20 °C. So the engine is **OWL 2 RL** over the data, and the process
ontology's RL module says what follows:

```turtle
proc:obtainedUnder owl:propertyChainAxiom ( [ owl:inverseOf proc:yielded ] proc:underCondition ) .
proc:plannedFor    owl:propertyChainAxiom ( proc:follows proc:plannedStep ) .
```

and the base module declares `obtained_under` a kind of `observed_under`. `entail` runs
the chain (`prp-spo2`) over what was extracted; every `obtained_under` link it derives
relates a result and a condition that were both already there, stands on the quotes of
the two links it came from, and is marked derived. `compare` then reads the graph as the
ontology makes it — the stored links and the derived ones, and every relation the ontology
puts under `observed_under` — so two results are compared on the conditions of the runs
that yielded them, and the answer can still say which of those relations nobody claimed.
`align` reads `planned_for` the same way. The chain goes through relations the extractor
asserts, so nothing is invented: a run whose condition nobody recorded still leaves its
result `insufficient`.

RL also turns two axioms into findings: plan and run are disjoint classes (information
against occurrent), and `directly_depends_on` is asymmetric, so a protocol recorded as a
performed experiment, or two computations recorded as consuming each other's output, are
**clashes** reported with both premises. A longer dependency cycle is not expressible as an
OWL 2 axiom on a transitive relation, which is why the `science_core` shapes check it in
closed world, with SHACL-SPARQL, before anything is asserted; the `process` shapes add a
warning on a result with no conditions recorded at all, and refuse a run recorded as
following two procedures.

## 5. Pipeline

### 5.1 Build

```
ingest_pdf → extract_llm → relocate → validate → relate_llm → relate → shacl_validate
           → assert → entail → align → index_nodes
```

Extraction is the ordinary chain: the ontology offers protocols, steps, runs, conditions and
results, and the model fills them against quotes it must supply verbatim.

`align` is the step specific to this architecture. It reads the two step lists out of
the store, pairs them, and reports four kinds of departure:

| Kind | Meaning |
|---|---|
| `missing` | Planned, and no step of the run matches it |
| `extra` | Carried out, and the procedure has no such step |
| `reordered` | Two steps whose order in the run does not follow their order in the procedure |
| `renamed` | Matched, under a different label |

The matcher is deliberately shallow — an asserted `realises` link first, then term
overlap between labels above a threshold. That is not an oversight. The value is in a
list of named departures somebody can read against the paper, not in an alignment good
enough to trust unread, and where the matcher is wrong the fix is to **assert** the
correspondence, which then carries a span like every other claim here.

A renamed step is reported rather than quietly matched, because "the procedure says
washing and the run says rinsing" is exactly the kind of difference that turns out to
matter.

### 5.2 Ask

```
index_nodes → retrieve → entail → graph_expand_entailed → compare → graph_answer
```

`compare` sorts the results of the evidence package against the first of them:

| Verdict | When |
|---|---|
| `comparable` | Every condition recorded on either side agrees — or something has asserted the two sets of conditions comparable, which is believed and named in the reason |
| `partial` | Both sides recorded a condition and they differ |
| `insufficient` | A condition recorded on one side is not recorded on the other, or the values are in units nothing declared a conversion between |

Three rules make this honest:

1. **Unknown is not equal**, and it is checked before difference: a hole in the evidence
   is a stronger statement than a mismatch.
2. **Both sides are read.** Earlier this compared only the conditions the baseline knew
   about, which meant a baseline that recorded nothing found that everything agreed —
   true, and the most misleading thing the step could say.
3. **A conversion is an act with provenance.** `Conversion` carries the factor and the
   unit the value started in. A unit pair the configuration did not declare makes the
   pair incomparable rather than assumed equal.

### 5.3 What a retraction reaches

`lineage` is not in the ask chain because it answers a different question, on demand:

```python
from atlas.steps.lineage import LineageOptions, lineage

affected = lineage(
    {"store": store, "cause": withdrawn_dataset_id},
    LineageOptions(follow=("derived_from", "used_dataset", "rests_on")),
)["affected"]
```

Every affected thing comes back with the **chain** that connects it to the cause, not
just its id: `("derived_from", "used_dataset")` reads from the affected result back to
the withdrawn archive. A list of ids is an alarm; a list of chains is something a person
can act on per item.

The relations are followed **against** the direction they are written in, because a
dependency relation points from the dependent thing to what it depends on, and the
question runs the other way. An ontology that writes them the other way round sets
`upstream: false`.

Nothing is retracted, marked or superseded. Writing is asserting: deciding a conclusion
is now in question is a judgement somebody records, and this step produces the list that
judgement has to consider.

## 6. What is stored

Beyond the shared argument layer:

- `Protocol` and `ProtocolStep` — the procedure as written, with an order.
- `Experiment` and `ExecutionStep` — the run and what happened in it, with an order.
- `ExperimentalCondition` — one condition, with its value and its unit.
- `PositiveResult` and `NegativeResult`, both subclasses of `StudyResult`.

That last line is the design decision worth defending. Modelling the outcome as a
boolean field on a result would have made *"what has been tried here and did not work"*
unanswerable by every query that finds results. As subclasses, negative results are
found by every search, ranked by every ranking, and pulled into every evidence package,
without a single special case anywhere.

## 7. Graph retrieval, exactly

```
question
  → rank nodes by term overlap → roots
  → entail: the RL closure, obtained_under and planned_for among what it derives
  → graph_expand_entailed: depth 3, budget 60, supports=[supports], opposes=[disputes]
      objections pulled in after the walk whatever the budget did
  → compare: results of the package, against the first
      conditions gathered from the result's own fields and from what
        `observed_under` / `under_condition` reaches, widened to every relation the
        ontology puts under them, stored or derived
      conversions applied only where declared, carrying the factor
      verdict per result, with the condition it was excluded on
  → graph_answer: entries, relations with direction, both sides named
```

The depth is 3 rather than 2 because the chain this architecture reasons over is longer:
claim → position → line of argument → result → conditions.

## 8. Evolution, with the case it was built for

A new report finds no effect, and mentions a preparation step the earlier work does not
describe. The wrong response is to lower a score on the original claim. The right one,
and the one the pipeline supports:

1. `align` reports the extra step in the new run.
2. `compare` puts the two results side by side and returns `insufficient`, naming the
   condition the earlier work did not record.
3. That named condition is the evidence for a schema proposal — a qualifier with a value
   type and a unit, or a type for the preparation process — which goes through review
   like any other change.
4. Until then, the explanation of the difference is a `Statement` with its own evidence,
   not an axiom.

## 9. Competency questions

| Question | The path | Why the process layer is needed |
|---|---|---|
| What has been tried and did not work? | `Experiment → yielded → NegativeResult → Statement` | A negative result is a result, found by every ordinary query |
| Which results are comparable? | `StudyResult → observed_under → Context`, then `compare` | Unknown conditions are excluded rather than assumed to match |
| Where does the run depart from the procedure? | `align` over `ProtocolStep` and `ExecutionStep` | Plan and run have separate identities |
| Which conclusions rest on this dataset? | `lineage` over `derived_from`, `used_dataset`, `rests_on` | The closure returns chains, not a set |

## 10. Risks and acceptance

- **Papers do not report process.** Most comparisons will come back `insufficient`. That
  is the finding, not a failure; the metric to watch is how often a condition is
  *recorded* per corpus, before any metric about agreement.
- **The step matcher is shallow and will be wrong.** By design, and visibly: every pair
  it makes on a different label is reported as `renamed`, and an asserted `realises`
  overrides it.
- **A conversion can still be scientifically wrong** even when the arithmetic is right —
  the same unit can mean different things in two protocols. The conversion carries its
  factor so that this is reviewable.

Acceptance: build a pair of results with near-identical text and different conditions.
If the system reports them as comparable, the architecture has not been implemented,
whatever the rest of it does.

## 11. Running it

```bash
atlas run architectures/a05.yaml corpus/*.pdf --store store/
atlas ask architectures/a05.yaml "under which conditions does the yield rise?" --store store/
```

## 12. Implementation

| Part | Where |
|---|---|
| Vocabulary | `ontologies/process.ttl`, `ontologies/process_rl.ttl`, `ontologies/science_core_rl.ttl`; shapes `ontologies/shapes/science_core.ttl`, `ontologies/shapes/process.ttl` |
| Engine | `atlas/reason/rl.py`, `atlas/steps/entail.py` (`implied`, `widen`); `atlas/steps/shacl_validate.py` |
| Plan against run | `atlas/steps/align.py` |
| Comparability and units | `atlas/steps/compare.py` (`compare`, `convert`, `Conversion`) |
| What a retraction reaches | `atlas/steps/lineage.py` |
| Manifest | `architectures/a05.yaml` |
| Tests | `tests/test_align.py`, `tests/test_compare.py` (a condition the chain carries), `tests/test_lineage.py`, `tests/test_rl.py`, `tests/test_shacl.py` |
