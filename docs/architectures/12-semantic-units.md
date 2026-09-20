# Architecture 12 — Semantic units and logic profiles

| | |
|---|---|
| **Id** | `a12` |
| **Manifest** | [`architectures/a12.yaml`](../../architectures/a12.yaml) |
| **Family** | Semantic-unit traversal |
| **Optimises** | Not flattening three different kinds of claim into one relation |
| **Score** | relevance 80, novelty 97, prospect 95, **total 89** — an engineering judgement, not a measurement |

## 1. What it is for

These are three different claims:

| Sentence | What establishes it | What refutes it |
|---|---|---|
| Some samples show the effect | one case | showing it never happens |
| Samples usually show the effect | counting | counting |
| All samples show the effect | checking every case | **one counterexample** |

A store that recorded all three as *"samples relate to effect"* has thrown away the
thing that decides what a counterexample means, and no amount of retrieval gets it back.
This architecture records the **form** of a claim beside the claim — kind, quantifier,
polarity, modality, scope — and rules mechanically on whether that form is complete
enough to be reasoned over.

## 2. What it is not

It is not a formalisation. A claim that does not translate exactly is kept, quoted and
retrieved; what it is refused is the status of a premise. The original wording is stored
in `expression` and never replaced by the formal reading — not out of caution, but
because what a translation loses is exactly what somebody later needs in order to find
out that it lost it.

It is also not a request to a model to decide what is provable. `compile_units` is
deterministic: whether a form is complete is a question about the record, and asking a
model would put the decision in the place least able to be checked.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core` + `semantic_units`. The pack declares the *fields* of a form and enumerates none of their values, because which distinctions matter is a property of the corpus. |
| **Reasoner** | None over data. `compile_units` is a completeness check, not an inference; what it licenses is that a unit *may* be used as a premise by something else. |
| **Data** | Units are read off the store per question, not asserted. The profile is a ruling about a record, and a ruling changes when the run's configuration does. |
| **Components and reuse** | `Schema.is_a` for the type test; `atlas.text.normalise` so that `"All"` and `"all "` are one value; the shared `Bundle`. |
| **Evolution** | A kind that keeps appearing and is not in the run's accepted list is the signal for a new template — and often for a qualifier rather than a new class, which is the mistake this architecture is best placed to avoid. |

## 4. The three profiles

| Profile | Meaning | What may be done with it |
|---|---|---|
| `exact` | Kind, quantifier, polarity and modality are all recorded and all accepted by the run | May be a premise |
| `lossy` | Recorded, but a formal reading would have to choose something | Retrieved, shown, quoted. Never a premise |
| `unsupported` | Something needed to read it at all is missing | Kept as what the source said, and nothing more |

The order the checks run in is the design:

1. **Polarity first, and hardest.** No polarity → `unsupported`, whatever else is
   recorded. A claim whose negation scope nobody recorded can mean either of two
   opposite things, and treating it as "mostly usable" is how a refutation becomes a
   confirmation.
2. A polarity the run does not read → `unsupported`.
3. No kind, or a kind the run does not interpret → `unsupported`: there is no form to
   read.
4. **No quantifier → `lossy`, not unsupported.** The claim is still about the thing it
   is about; what is lost is how much of it is claimed.
5. A modality the run does not read → `lossy`.
6. Otherwise `exact`.

Every ruling carries its `reason`, in words, because "unsupported" with no reason is
indistinguishable from a bug.

**With nothing configured, nothing is exact.** `kinds`, `quantifiers`, `polarities` and
`modalities` have no defaults. That is the safe direction to fail in, and it also keeps
the words of a language out of this package, which holds none.

## 5. Pipeline

### 5.1 Build

```
formal_check → ingest_pdf → extract_llm → relocate → validate
             → relate_llm → relate → assert → index_nodes
```

`SemanticUnit` is an ordinary type of the pack, so the extractor fills its fields like
any other and every unit is bound to a verbatim span. `expresses` relates a proposition
to its form; `counterexample_to` relates a result to a unit, which is the relation that
only bites on some kinds; `holds_under` relates a unit to the conditions it is
restricted to.

### 5.2 Ask

```
index_nodes → compile_units → retrieve → graph_expand → mark_units → graph_answer
```

`mark_units` writes each unit's form and profile into the package's `reasons`, where the
answering prompt already prints them as `selected: …`. So the model sees

```
[paper-1#4f21a0] all samples show the effect (SemanticUnit)
  > All samples show the effect.
  selected: ranked 0.612; universal, all, affirmative; exact: kind, quantifier,
            polarity and modality are all ones this run reads
```

and can write *"this is a universal claim, and this counterexample refutes it"* rather
than treating three kinds of statement as one.

**Nothing is filtered.** A unit that may not be reasoned over is still what a source
said; dropping it would lose the evidence along with the inference. That is tested
(`test_a_unit_that_may_not_be_reasoned_over_is_still_in_the_package`).

## 6. Graph retrieval, exactly

```
question
  → compile_units over the store: a ruling per unit, with its reason
  → rank nodes → roots
  → graph_expand: depth 3, budget 60, objections kept against the budget
  → mark_units: form and profile into the package's reasons
  → graph_answer: the form is in front of the model beside the evidence
```

Where an inference layer is wired in, `provable_only(units)` is what it is given — the
exact ones, and nothing else. It is offered as a function so that a configuration cannot
get the direction wrong by accident.

## 7. Evolution, with the case it prevents

The corpus starts saying *"the method applies only if …"*. The old profile had a plain
binary relation and lost the condition. The proposal is a **conditional template**, which
refers to existing concepts of conditions.

What must not happen — and what this architecture is best placed to prevent — is a new
class for each grammatical construction. The right change is usually a qualifier or a
shape, not a type; `formal_check` has nothing to say about that, and the discipline is
the review, informed by how many units came back `unsupported` for the same reason.

The new template is then run against pairs of examples that differ only in the scope of
a negation. That is the adversarial case, and a template that passes it on pretty
examples and fails it there has not been tested.

## 8. Competency questions

| Question | What the form gives |
|---|---|
| Is this a universal claim or a single observation? | `kind` and `quantifier`, recorded rather than inferred from wording |
| Which counterexamples bear on this conditional? | `counterexample_to` plus `holds_under`, rather than text similarity |
| Which parts of the answer were formally checked? | `profile` on every unit, in the package, in front of the model |

## 9. Risks and acceptance

- **A great deal will come back unsupported** on a corpus whose sentences do not state
  their own quantifiers. That is the honest reading, and the number to watch: a corpus
  where everything is exact has an extractor that is guessing.
- **Imitating understanding.** The adversarial cases are negation scope and quantifier,
  not pretty examples. A template that only works on sentences that already state their
  form is a template that does nothing.
- **This is the most bespoke semantics in the library**, and therefore the most work to
  keep true. Its high novelty score and lower relevance score say exactly that.

Acceptance: the three sentences in §1 must come out as three units with three different
kinds and quantifiers, and a claim with no recorded polarity must come out `unsupported`
rather than `lossy`. Both are tested.

## 10. Running it

```bash
atlas run architectures/a12.yaml corpus/*.pdf --store store/
atlas ask architectures/a12.yaml "is this a universal claim or a single observation?" --store store/
```

## 11. Implementation

| Part | Where |
|---|---|
| Vocabulary | `packs/semantic_units.yaml` |
| Reading a form and ruling on it | `atlas/steps/units.py` (`read`, `judge`, `compile_units`) |
| Putting the form in front of the answer | `atlas/steps/units.py` (`mark_units`) |
| What may be a premise | `atlas/steps/units.py` (`provable_only`) |
| Manifest | `architectures/a12.yaml` |
| Tests | `tests/test_units.py` |
