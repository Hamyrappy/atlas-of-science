# Architecture 10 — Materialised entailment with derivation provenance

| | |
|---|---|
| **Id** | `a10` |
| **Manifest** | [`architectures/a10.yaml`](../../architectures/a10.yaml) |
| **Family** | Entailment traversal |
| **Optimises** | Asking a question the ontology already answers, without a reasoner at query time |
| **Score** | relevance 86, novelty 79, prospect 90, **total 86** — an engineering judgement, not a measurement |

## 1. What it is for

A pack that declares a relation transitive has said something executable. If A is part of
B and B is part of C then A is part of C, and a question about A ought to find C without
anybody having asserted the third link. This architecture computes those consequences
ahead of the question — which makes them cheap to query — and keeps for every one of
them the premises and the rule it came from, which is what makes them safe to use.

The interesting question is not how to compute a closure. It is how to keep one without
turning the graph into a place where you cannot tell what anybody claimed.

## 2. What it is not

It is not a reasoner, and it says so in its type: three rules — transitive, symmetric,
inverse — because those are the three a pack can declare and a closure can compute
without either a real reasoner or a decision about what to do when it fails to
terminate. A pack that declares a fourth gets a `formal_check` problem naming the three
this library executes.

It also does not put inferences in the store. Derived links come back as a separate
collection; `assert_derived` exists and is off, and a run that turns it on is recording
that *the system* inferred this, under an agent of its own.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core` + `science_map`. What matters is the RBox: `part_of` transitive, `has_part` its inverse, `comparable_with` symmetric, `narrower` transitive. |
| **Reasoner** | The closure in `atlas/steps/entail.py`, run at question time over admitted relations, plus `formal_check` over the schema at build time. Nothing at query time is open-world. |
| **Data** | The store for what was claimed; the closure for what follows, computed per question and not written. |
| **Components and reuse** | `Schema.with_characteristic`, `Schema.inverse`, the shared `expand` with a supplied adjacency. |
| **Evolution** | A new axiom changes the closure and therefore the answers, so old and new must be compared before release. A retraction is computed rather than assumed — see §5. |

## 4. Pipeline

### 4.1 Build

```
formal_check → ingest_pdf → extract_llm → relocate → validate
             → relate_llm → relate → assert → index_nodes
```

`formal_check` runs **first** and strictly: an axiom set that cannot be satisfied would
have every node written under it written under a contradiction, and finding out later
means re-extracting the corpus.

### 4.2 Ask

```
index_nodes → retrieve → entail → graph_expand_entailed → graph_answer
```

`entail` closes the admitted relations. `graph_expand_entailed` walks the asserted links
and the derived ones together, and marks in the package which are which.
`graph_answer` shows a derived relation as *"(inferred, not stated by any source)"* and
the prompt tells the model to write that it follows rather than that a source reports
it.

## 5. The four rules, and why each one is there

**Derived is never asserted.** A derived link carries the **spans of its premises**
rather than one of its own. No text says the consequence, and inventing a span for it
would put a claim in the store that nothing supports — which is invariant 1 of this
library, applied to inference. It also carries `fields["derived"]` naming the rule, so a
reader can tell an inference from a claim by looking at the object.

**Every derived link carries its derivation.** Premises, rule, and the schema version
the rule came from. A consequence nobody can explain is a consequence nobody can check.

**Only admitted premises are used.** `premises` names the relations that may be reasoned
over. This is what keeps *"the author disputes P"* from becoming *"not P"* anywhere in
the graph: the closure runs over relations the configuration admitted, not over
everything in the store.

**Retraction is computed, not assumed.** And this is the part that is easy to get wrong:

> A derived relation can be a premise of another derived relation, and two of them can
> support each other in a circle — A implies B by one rule, B implies A by another.

Marking downwards from what was withdrawn leaves such a pair standing on nothing but
itself, and reports a retraction as harmless when it was not. So `supported` builds the
standing set **upwards**: start with the asserted links that were not withdrawn, then
repeatedly add any derived link one of whose derivations has all its premises already
standing. `test_two_derived_links_supporting_each_other_do_not_stand_on_nothing` is that
case written down.

`invalidated` then returns two collections: what has fallen, and what was shaken and
**still follows on other grounds**. Reporting the second as lost would overstate what a
retraction cost, and a reviewer reads it to know what *not* to recheck.

## 6. One consequence, several derivations

A consequence that follows two ways is one relation, not two: deduplicating by what is
related is what stops a closure growing a copy per path. But **both derivations are
kept**, because that is exactly what answers the question after a retraction. In
`test_a_consequence_that_follows_two_ways_survives_losing_one_of_them`, `a part_of c`
follows through `b` and through `d`; withdrawing the first chain leaves the relation
standing, and the report says so rather than listing it as lost.

## 7. Graph retrieval, exactly

```
question
  → rank nodes → roots
  → entail: for rounds, apply symmetric / inverse / transitive together
        dedupe links by (predicate, src, dst); keep every derivation
        stop at a fixed point, or report `finished: false`
  → Adjacency over asserted ∪ derived
  → expand: depth 3, budget 80, objections pulled in whatever the budget did
  → mark which links were inferred
  → graph_answer: derived relations rendered "(inferred, not stated by any source)"
```

A closure that did not settle within its rounds reports `closure_finished: false` rather
than presenting a truncated closure as complete.

## 8. Competency questions

| Question | What the closure gives |
|---|---|
| What is this part of, at any remove? | The transitive closure, without anybody asserting each step |
| Why is this relation in the answer? | Its derivation: premises, rule, schema version |
| What falls if this is withdrawn? | `invalidated`, in two parts |

## 9. Risks and acceptance

- **Closure size.** It grows with the transitive relations declared. `rounds` bounds it
  and an unfinished closure is reported; a corpus where that keeps happening has a
  transitive relation it should not have declared.
- **A derived relation is not a scientific fact.** It follows from the axioms and from
  the premises admitted. The prompt marking and the `derived` list on the package are
  what keep that visible; they are the part to check first if an answer reads oddly.
- **Comparing speeds is misleading.** The query is fast because the closure was computed;
  measure the update *and* the query, not the query.

## 10. Running it

```bash
atlas run architectures/a10.yaml corpus/*.pdf --store store/
atlas ask architectures/a10.yaml "what is this a part of, at any remove?" --store store/
```

## 11. Implementation

| Part | Where |
|---|---|
| Relation axioms in the pack | `atlas/model/schema.py` (`characteristics`, `inverse_of`, `with_characteristic`, `inverse`) |
| The closure and its provenance | `atlas/steps/entail.py` (`close`, `Derivation`, `supported`, `invalidated`) |
| Walking asserted and derived together | `atlas/steps/entail.py` (`graph_expand_entailed`) |
| Marking inference in the answer | `atlas/steps/graph_answer.py` (`relations`) |
| Manifest | `architectures/a10.yaml` |
| Tests | `tests/test_entail.py` |
