# Architecture 10 — Materialised entailment with derivation provenance

| | |
|---|---|
| **Id** | `a10` |
| **Manifest** | [`architectures/a10.yaml`](../../architectures/a10.yaml) |
| **Family** | Entailment traversal |
| **Optimises** | Asking a question the ontology already answers, without a reasoner at query time |
| **Score** | relevance 86, novelty 79, prospect 90, **total 86** — an engineering judgement, not a measurement |

## 1. What it is for

An ontology that declares a relation transitive has said something executable. If A is part of
B and B is part of C then A is part of C, and a question about A ought to find C without
anybody having asserted the third link. This architecture computes those consequences
ahead of the question — which makes them cheap to query — and keeps for every one of
them the premises and the rule it came from, which is what makes them safe to use.

The interesting question is not how to compute a closure. It is how to keep one without
turning the graph into a place where you cannot tell what anybody claimed.

## 2. What it is not

It is not a reasoner for all of OWL. It runs the OWL 2 RL rule table and nothing else,
because RL is the profile whose closure is finite, computable by rules, and made only of
facts about individuals that were already there. An ontology that needs more — a union on
the right, an existential that would introduce a new individual — is outside the profile
the manifest names and is refused when the configuration is read.

It also does not put inferences in the store. Derived links come back as a separate
collection; `assert_derived` exists and is off, and a run that turns it on is recording
that *the system* inferred this, under an agent of its own.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core_rl` + `science_map_rl`, under `profile: RL`. What matters is what the RL modules add: `part_of` and `depends_on` transitive, `has_part` the inverse of `part_of`, `comparable_with` symmetric, `directly_depends_on` asymmetric, `supports` and `disputes` disjoint, the chains behind `computed_from_data` and `in_topic`, `narrower` transitive, and the sufficient conditions of the defined classes. |
| **Reasoner** | OWL 2 RL, the whole rule table, over the data (`entail`, at question time), with a derivation for every consequence and every clash; the DL tableau over the ontology at build time (`formal_check: {engine: dl}`). Nothing at query time is inferred outside that closure. |
| **Data** | The store for what was claimed; the closure for what follows, computed per question and not written. |
| **Components and reuse** | `Schema.with_characteristic`, `Schema.inverse`, the shared `expand` with a supplied adjacency. |
| **Evolution** | A new axiom changes the closure and therefore the answers, so old and new must be compared before release. A retraction is computed rather than assumed — see §6. |

## 4. The ontology and the engine

This is the architecture the OWL 2 RL profile was written for. RL is the fragment of OWL 2
whose consequences can be computed by forward-chaining rules — the W3C publishes the rule
table — and no rule in it concludes that an individual exists: every consequence relates
things that were already in the graph. That is what makes it safe to run over extracted
data and keep, and `atlas/reason/rl.py` implements the table:

| family | rules | what it gives this corpus |
|---|---|---|
| relations | `prp-trp`, `prp-symp`, `prp-inv`, `prp-spo1`, `prp-spo2`, `prp-eqp` | transitive parthood and dependency, symmetric comparability, inverses, sub-relations, property chains |
| signatures | `prp-dom`, `prp-rng` | a node's classes from the relations it stands in |
| classes | `cax-sco`, `cax-eqc`, `cls-int`, `cls-uni`, `cls-svf`, `cls-hv`, `cls-avf` | the hierarchy, and membership of a defined class from its sufficient condition |
| clashes | `cax-dw`, `prp-pdw`, `prp-asyp`, `prp-irp`, `cls-nothing`, `cls-com`, `cls-maxc` | two facts the ontology says cannot both hold, with both premises |
| identity | `prp-fp`, `prp-ifp`, `eq-sym`, `eq-trans`, `eq-rep` | two nodes that must be one individual, when a relation says so |

The profile is a contract. The manifest names `RL`, and an axiom outside it — a union on
the right, an existential on the right, a cardinality above one — is refused when the
configuration is read, rather than silently ignored by the rules. The ontology itself is
checked at build time by the DL tableau, which is complete for more than RL can say, so a
contradiction in the axioms stops the run before anything is written under it.

## 5. Pipeline

### 5.1 Build

```
formal_check{dl} → ingest_pdf → extract_llm → relocate → validate
             → relate_llm → relate → assert → index_nodes
```

`formal_check` runs **first**, strictly, with the DL tableau: an axiom set that cannot
be satisfied would
have every node written under it written under a contradiction, and finding out later
means re-extracting the corpus.

### 5.2 Ask

```
index_nodes → retrieve → entail → graph_expand_entailed → graph_answer
```

`entail` closes the stored graph under the OWL 2 RL rules. `graph_expand_entailed` walks the asserted links
and the derived ones together, and marks in the package which are which.
`graph_answer` shows a derived relation as *"(inferred, not stated by any source)"* and
the prompt tells the model to write that it follows rather than that a source reports
it.

## 6. The four rules, and why each one is there

**Derived is never asserted.** A derived link carries the **spans of its premises**
rather than one of its own. No text says the consequence, and inventing a span for it
would put a claim in the store that nothing supports — which is invariant 1 of this
library, applied to inference. It also carries `fields["derived"]` naming the rule, so a
reader can tell an inference from a claim by looking at the object.

**Every derived link carries its derivation.** Premises, rule, and the schema version
the rule came from. A consequence nobody can explain is a consequence nobody can check.

**Only admitted premises are used.** `premises` names the relations that may be reasoned
over, and a configuration over a loosely written ontology names a few. This manifest
admits every relation, because the RL modules were written for rules to run over, and
nothing in them turns *"the author disputes P"* into *"not P"*: `disputes` is a relation
to a proposition, never a negation of it, and the only thing the ontology derives from it
is that the proposition is contested.

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

## 7. One consequence, several derivations

A consequence that follows two ways is one relation, not two: deduplicating by what is
related is what stops a closure growing a copy per path. But **both derivations are
kept**, because that is exactly what answers the question after a retraction. In
`test_a_consequence_that_follows_two_ways_survives_losing_one_of_them`, `a part_of c`
follows through `b` and through `d`; withdrawing the first chain leaves the relation
standing, and the report says so rather than listing it as lost.

## 8. Graph retrieval, exactly

```
question
  → rank nodes → roots
  → entail: for rounds, apply the OWL 2 RL rule table
        dedupe facts by (subject, predicate, object); keep every derivation
        a clash is reported with its premises, never resolved
        stop at a fixed point, or report `finished: false`
  → Adjacency over asserted ∪ derived; inferred classes into the reasons
  → expand: depth 3, budget 80, objections pulled in whatever the budget did
  → mark which links were inferred
  → graph_answer: derived relations rendered "(inferred, not stated by any source)"
```

A closure that did not settle within its rounds reports `closure_finished: false` rather
than presenting a truncated closure as complete.

## 9. Competency questions

| Question | What the closure gives |
|---|---|
| What is this part of, at any remove? | The transitive closure, without anybody asserting each step |
| Why is this relation in the answer? | Its derivation: premises, rule, schema version |
| What falls if this is withdrawn? | `invalidated`, in two parts |

## 10. Risks and acceptance

- **Closure size.** It grows with the transitive relations declared. `rounds` bounds it
  and an unfinished closure is reported; a corpus where that keeps happening has a
  transitive relation it should not have declared.
- **A derived relation is not a scientific fact.** It follows from the axioms and from
  the premises admitted. The prompt marking and the `derived` list on the package are
  what keep that visible; they are the part to check first if an answer reads oddly.
- **Comparing speeds is misleading.** The query is fast because the closure was computed;
  measure the update *and* the query, not the query.

## 11. Running it

```bash
atlas run architectures/a10.yaml corpus/*.pdf --store store/
atlas ask architectures/a10.yaml "what is this a part of, at any remove?" --store store/
```

## 12. Implementation

| Part | Where |
|---|---|
| The axioms | `ontologies/science_core_rl.ttl`, `ontologies/science_map_rl.ttl`, read into `atlas/model/owl.py` |
| The rule engine | `atlas/reason/rl.py` (`reason`, `Closure`, `supported`), `atlas/reason/facts.py` (`Derivation`, `Clash`) |
| The gate | `atlas/reason/tableau.py`, `atlas/steps/formal_check.py` |
| The closure and its provenance | `atlas/steps/entail.py` (`close`, `Derivation`, `supported`, `invalidated`) |
| Walking asserted and derived together | `atlas/steps/entail.py` (`graph_expand_entailed`) |
| Marking inference in the answer | `atlas/steps/graph_answer.py` (`relations`) |
| Manifest | `architectures/a10.yaml` |
| Tests | `tests/test_entail.py`, `tests/test_rl.py`, `tests/test_tableau.py` |
