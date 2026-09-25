# Architecture 6 — Critic, bounded repair and conflict review

| | |
|---|---|
| **Id** | `a06` |
| **Manifest** | [`architectures/a06.yaml`](../../architectures/a06.yaml) |
| **Family** | Typed traversal with review |
| **Optimises** | The cost of a wrong record, and knowing which errors were which |
| **Score** | relevance 89, novelty 91, prospect 93, **total 91** — an engineering judgement, not a measurement |

## 1. What it is for

Every other architecture here trusts a single extraction pass. This one does not, and
the question it is built around is the one that decides whether a corpus of markup is
worth anything: **when two records disagree, is that the field disagreeing or is it us
getting it wrong?**

It adds three reviews at three different places:

1. **Before anything is asserted** — deterministic critics compare each node with its
   own span and its own type, and what they find repairable goes back to the model with
   a budget.
2. **When two positions oppose each other** — the pair is classified, and a genuine
   disagreement is kept rather than resolved.
3. **After the answer is written** — the answer is checked against the package it came
   from, for the side it left out.

## 2. What it is not

It is not a debate between agents, and it is not an unbounded reflection loop. The
repair budget is two attempts by default, and what survives it is **quarantined** —
held out of what the run asserts, with the findings that condemned it — because an
exhausted budget must never turn into an acceptance. `quarantined` is a list of cases;
`repaired` is a count; a run reports both and the difference between them is the thing
worth reading.

It is also not a voting system. `reconcile` never picks a winner and never removes
anything from a store. Its verdicts are about what has been *established* about a pair,
and `disagreement` is the default — what you get when nothing else is established, not
what you get when two models agree it is one.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core_rl` + `scierc_rl` (each imports its base module), under `profile: RL`, with the shapes `science_core` and `critic`. Unchanged in vocabulary by this architecture: what differs is how much checking a record survives before it is written. |
| **Reasoner** | Two halves. SHACL (`shacl_validate`) is the closed-world critic of the record before it is asserted; OWL 2 RL (`entail`) over the stored graph at question time reports every clash — two claims the ontology proves cannot both hold — with both premises. The critics of `critique` are deterministic and local; the one model call in the loop is the repair, not the judgement. |
| **Data** | The store as everywhere else, plus quarantine and findings in the run state. A quarantined node is not asserted, so it never reaches the graph. |
| **Components and reuse** | `atlas.text.fold` for grounding checks; the shared `Bundle`; `keep_cited` inherited by `graph_answer`. |
| **Evolution** | Findings that recur are the evidence for a change. Ten documents that all confuse a description with a performance are one extraction problem or one missing distinction, and the findings say which. |

## 4. The ontology and the engine

A critic is a check that can say *this record is wrong* without asking a model whether it
is. Two of those are not written in Python here; they are the ontology's.

**SHACL, in closed world, before anything is asserted.** `shacl_validate` runs after the
relations are located and before `assert`, against the shapes the ontology implies — each
class closed over its own fields, every node on a span, each relation's domain and range
as a class the record must already have — and the shapes the manifest names:
`science_core` (a statement on one proposition only, a proposition that records what it
claims, a computation that depends on itself through a chain) and `critic` (a mention
that records its name, a quote long enough to locate anything, a method compared with
itself). A violation refuses the object with the shape's own message; a warning keeps it.
This is the part of criticism that OWL cannot do: under the open-world assumption a
proposition with no expression is one whose expression nobody mentioned, and no reasoner
will complain.

**OWL 2 RL, over the stored graph, at question time.** `supports` and `disputes` are
disjoint relations and the six SciERC labels disjoint classes, so a line recorded as both
for and against one proposition, or one mention typed as a method and a task, is a
**clash** (`prp-pdw`, `cax-dw`) with both premises named. A clash is the ontology proving
two extracted claims cannot both be true — which is exactly what `reconcile` then has to
distinguish from a genuine disagreement. The closure's derived links go into the package
marked as inference, and `reconcile` reads conditions through what the engine derived and
through every relation the ontology puts under the ones configured.

## 5. Pipeline

### 5.1 Build

```
ingest_pdf → extract_llm → relocate → critique → repair_llm → relocate → validate
           → relate_llm → relate → shacl_validate → assert → index_nodes
```

`relocate` runs twice, and the second one is not a mistake. `repair_llm` returns **one
uniform stream of statements**: the untouched nodes turned back into the claims they
were made from, plus the corrected ones. Placing a quote is deterministic, so an
untouched node is placed at the same offsets and hashes to exactly the id it already
had — and the alternative, returning two collections for a later step to union, is a
seam where half a run's nodes get dropped by whoever forgets. This is tested
(`test_an_untouched_node_re_placed_hashes_to_the_id_it_already_had`).

**The critics.** Five checks, each local and deterministic:

| Check | What it means | Repairable |
|---|---|---|
| `untyped` | The class is not one the ontology declares | no |
| `unnamed` | Nothing fills the field that names it, so it reads as its type | yes |
| `thin` | The whole evidence is shorter than the configured minimum | yes |
| `ungrounded` | A field's value does not appear in the quote it was taken from | yes |
| `negation` | The quote carries a configured negation marker | **no** |

The negation check is the one worth explaining. "No increase was observed" is a
perfectly good negative result, correctly extracted — so the check reports rather than
judges, and it is deliberately **not repairable**: the extractor already read the
sentence, and what to make of it is a question about meaning that asking again does not
settle. The markers are configured, because negation markers are words of a language and
this package holds none: with nothing named, nothing is found.

**The repair.** Each repairable node goes back with its findings, its own quote and its
source segment, at most `rounds` times. A reply saying `withdraw` ends the loop; a reply
that cannot be read spends one attempt rather than all of them. What comes out is a
statement for `relocate`, never a patched node — a node is a content hash over its type,
its fields and its span, so a "repaired" node is a different node and pretending
otherwise would put two claims under one id.

### 5.2 Ask

```
index_nodes → retrieve → entail → graph_expand_entailed → reconcile → graph_answer → check_answer
```

**`reconcile`** pairs the opposed positions of the package and decides between four
verdicts. The order the checks run in is part of the claim:

1. Both positions rest on the **same words** → `extraction`: one sentence read two ways.
2. **Recorded conditions differ** → `conditions`. Checked *before* the source, because
   one paper reporting an effect under one set of conditions and none under another is
   the conditions case, not a paper contradicting itself. Checking the source first
   would have hidden exactly the finding worth recording.
3. **One source, same recorded conditions, both sides** → `ambiguous`.
4. Otherwise → `disagreement`.

**`check_answer`** reviews the finished answer against its package. `graph_answer`
already drops a line that cites nothing or cites something that was not shown; this asks
what that rule cannot:

- does every citation resolve to a node of the package;
- if the package held positions on **both** sides, does the answer cite both;
- was the package partial, and does the reader know.

The second is the point. An answer whose every line is cited and whose every citation is
real can still have turned a controversy into a consensus by leaving one side out. A
side counts as cited when the answer cites either end of one of its relations — the
position, or the claim it is about — because that is how an answer to this kind of
question is actually written. And a one-sided package answered one-sidedly is complete:
one-sided evidence answered one-sidedly is a complete answer to the evidence there was.

Nothing is appended and nothing is rewritten. The review is a verdict and a list; acting
on it is the configuration's decision, and a step that quietly added the missing side
would be writing prose nobody checked.

## 6. What is stored

The same as architecture 0's vocabulary plus the argument layer — this architecture
changes the *process*, not the record. Two things stay out of the store on purpose:
findings and quarantined nodes. A quarantined node was never asserted, so the graph
never held it; a run reports it, and a person deciding to accept it does so by asserting
it, which is how everything else enters this library too.

## 7. Graph retrieval, exactly

```
question
  → rank nodes by term overlap → roots
  → entail: the RL closure, with every clash and its premises
  → graph_expand_entailed: depth 3, budget 60, supports/opposes named, derived links marked
  → reconcile: for each (supporting, opposing) pair on one claim
        same words?            → extraction
        conditions differ?     → conditions      (before the source check)
        one source?            → ambiguous
        otherwise              → disagreement    (the default)
  → graph_answer: entries, relations with direction, both sides named
  → check_answer: citations resolve? both sides cited? package partial?
```

## 8. Evolution, from a pattern of findings

Ten documents produce nodes where a description of a method is typed as the performance
of it. Three things could be true, and the findings distinguish them:

- the extractor's prompt is wrong → fix the prompt, no schema change;
- the grounding is wrong → the critic's `ungrounded` findings will say so;
- the **schema** lacks the distinction → and only then is it a schema change.

Often the third is already covered by the imported vocabulary — `science_core` declares
`InformationEntity` and `Process` disjoint — and the right change is a bridge or an
extraction rule, not two new local types. Any change is then run against the earlier
wrong *and* right cases: records that were correct must stay correct.

## 9. Competency questions

| Question | What it uses |
|---|---|
| Why was this statement corrected? | The finding, the repair prompt, the resulting statement |
| Is this a scientific conflict or an extraction error? | `Conflict.verdict` with its reason and the two quotes |
| Which side did the answer leave out? | `Review.omitted` |
| What did this run refuse to assert? | `quarantined`, with the findings on each |

## 10. Risks and acceptance

- **Correlated errors.** A critic from the same model family misses exactly the mistakes
  that model reliably makes. The deterministic critics are immune to this and the
  repair is not, which is why the critics are deterministic.
- **Cost.** Up to two extra calls per questionable node. The number to measure is
  *errors corrected minus errors introduced* per unit of extra cost — not the count of
  repairs, which goes up either way.
- **Over-reporting.** A critic that fires on everything is as useless as one that fires
  on nothing; `min_quote` and `grounded_fields` are the dials, and the per-check counts
  are what to read before turning them.

Acceptance: run the same corpus through architecture 0 and this one, and compare the
records they disagree about by hand. If the repairs are not better than the originals
more often than they are worse, the loop costs money and buys nothing.

## 11. Running it

```bash
atlas run architectures/a06.yaml corpus/*.pdf --store store/
atlas ask architectures/a06.yaml "do these two papers disagree?" --store store/
```

## 12. Implementation

| Part | Where |
|---|---|
| Vocabulary | `ontologies/science_core_rl.ttl`, `ontologies/scierc_rl.ttl`; shapes `ontologies/shapes/science_core.ttl`, `ontologies/shapes/critic.ttl` |
| Engines | `atlas/reason/shacl.py`, `atlas/steps/shacl_validate.py`; `atlas/reason/rl.py`, `atlas/steps/entail.py` |
| Critics | `atlas/steps/critique.py` (`critique`, `Finding`, `repairable`) |
| Bounded repair and quarantine | `atlas/steps/repair.py` |
| Conflict review | `atlas/steps/reconcile.py` |
| Answer review | `atlas/steps/check_answer.py` |
| Manifest | `architectures/a06.yaml` |
| Tests | `tests/test_critique.py`, `tests/test_shacl_validate.py`, `tests/test_rl.py`, `tests/test_reconcile.py`, `tests/test_check_answer.py` |
