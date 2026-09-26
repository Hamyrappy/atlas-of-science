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
| **Schema** | `science_core_el` + `semantic_units`, under `profile: EL`. The ontology declares the *fields* of a form and enumerates none of their values, because which distinctions matter is a property of the corpus. |
| **Reasoner** | OWL 2 EL, over the ontology and the units. `compile_units` rules on a form's completeness — which is not an inference — and then translates each exact unit into an OWL axiom and runs the EL classifier over the ontology with every universal one: what already follows, and which units contradict each other. `formal_check` (EL) gates the ontology at build time. Nothing is inferred over the data. |
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

## 5. The unit as OWL, and the EL engine

A unit ruled `exact` is complete enough to be a premise, and here it is used as one. It
relates two terms, and a term the ontology has a class for is that class; any other term
is a class of the run's own, named after the words. Which quantifier words read as *all*,
*some* and *none*, and which polarities negate, are the manifest's (`readings`,
`negative`); a word nobody mapped is not translated, however exact its form.

| form | as OWL | is |
|---|---|---|
| all S are O | `SubClassOf(S, O)` | a terminological axiom |
| no S are O, all S are not O | `DisjointClasses(S, O)` | a terminological axiom |
| some S are O | `S ⊓ O` has a member | a claim of existence — checked, never added |
| some S are not O | `S ⊓ ¬O` has a member | the same |

A universal claim is a statement about classes, so it joins the ontology for the length of
the check. An existential claim is about individuals: adding it would be the engine
inventing a member nobody named, which nothing in this library does over data, so it is
only checked against what the ontology and the universal units imply.

The EL classifier (`atlas/reason/el.py`) runs twice — over the ontology alone, and over the
ontology with every universal unit — and each translated unit gets one status:

- **`follows`** — the ontology alone already implies it. The source restated the
  vocabulary; worth knowing before counting it as a finding.
- **`contradicted`** — the ontology with the other units makes it false: two universals
  that together leave a term with no possible member (a claim about a kind of thing
  presupposes the kind has members), or an existence claim that a disjointness rules out.
  The unit names the **fewest** other units the contradiction needs, found by removing
  units one at a time and keeping only those it cannot do without, and `unit_conflicts`
  lists each set once. An existence claim contradicted by nothing but the ontology names
  no other unit, and the conflict says the ontology rules it out.
- **`consistent`** — otherwise.

Each translated unit also records the axiom in functional syntax and the OWL 2 profiles
that axiom is in, and `mark_units` puts both, with the status, into the reason the unit is
in the package. Nothing is dropped for a contradiction: two sources whose universal claims
cannot both hold are exactly what a reader must see, quoted, side by side.

## 6. Pipeline

### 6.1 Build

```
formal_check{el} → ingest_pdf → extract_llm → relocate → validate
             → relate_llm → relate → assert → index_nodes
```

`SemanticUnit` is an ordinary class of the ontology, so the extractor fills its fields like
any other and every unit is bound to a verbatim span. `expresses` relates a proposition
to its form; `counterexample_to` relates a result to a unit, which is the relation that
only bites on some kinds; `holds_under` relates a unit to the conditions it is
restricted to.

### 6.2 Ask

```
index_nodes → compile_units → retrieve → graph_expand → mark_units → graph_answer
```

`compile_units` rules on every unit and translates and checks the exact ones (§5).
`mark_units` writes each unit's form, profile, OWL reading and status into the package's
`reasons`, where the
answering prompt already prints them as `selected: …`. So the model sees

```
[paper-1#4f21a0] all samples show the effect (SemanticUnit)
  > All samples show the effect.
  selected: ranked 0.612; universal, all, affirmative; exact: kind, quantifier,
            polarity and modality are all ones this run reads; as OWL:
            SubClassOf(unit-term:samples unit-term:show the effect)
```

and can write *"this is a universal claim, and this counterexample refutes it"* rather
than treating three kinds of statement as one.

**Nothing is filtered.** A unit that may not be reasoned over is still what a source
said; dropping it would lose the evidence along with the inference. That is tested
(`test_a_unit_that_may_not_be_reasoned_over_is_still_in_the_package`).

## 7. Graph retrieval, exactly

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

## 8. Evolution, with the case it prevents

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

## 9. Competency questions

| Question | What the form gives |
|---|---|
| Is this a universal claim or a single observation? | `kind` and `quantifier`, recorded rather than inferred from wording |
| Which counterexamples bear on this conditional? | `counterexample_to` plus `holds_under`, rather than text similarity |
| Which parts of the answer were formally checked? | `profile` on every unit, in the package, in front of the model |

## 10. Risks and acceptance

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

## 11. Running it

```bash
atlas run architectures/a12.yaml corpus/*.pdf --store store/
atlas ask architectures/a12.yaml "is this a universal claim or a single observation?" --store store/
```

## 12. Implementation

| Part | Where |
|---|---|
| Vocabulary | `ontologies/semantic_units.ttl`, `ontologies/science_core_el.ttl` |
| The unit as OWL, and its judgement | `atlas/steps/units.py` (`translate`, `judge_all`, `Conflict`); `atlas/reason/el.py` |
| Reading a form and ruling on it | `atlas/steps/units.py` (`read`, `judge`, `compile_units`) |
| Putting the form in front of the answer | `atlas/steps/units.py` (`mark_units`) |
| What may be a premise | `atlas/steps/units.py` (`provable_only`) |
| Manifest | `architectures/a12.yaml` |
| Tests | `tests/test_units.py`, `tests/test_el.py` |
