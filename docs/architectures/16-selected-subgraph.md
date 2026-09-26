# Architecture 16 — Prize-collecting subgraph selection

| | |
|---|---|
| **Id** | `a16` |
| **Manifest** | [`architectures/a16.yaml`](../../architectures/a16.yaml) |
| **Family** | Selected-subgraph traversal |
| **Optimises** | A vague question, where a fixed-depth walk is the wrong shape |
| **Score** | relevance 72, novelty 95, prospect 90, **total 84** — an engineering judgement, not a measurement |

## 1. What it is for

*"What connects these two lines of work?"* does not translate into a pattern. A walk of
fixed depth from ranked seeds answers it badly in both directions: two hops from a
strong seed reaches a hundred nodes of which four matter, and two hops from a weak one
reaches nothing at all.

What the question wants is a **small connected region** holding the valuable nodes and as
little else as possible. That is the prize-collecting Steiner tree problem — prizes on
nodes, costs on edges, maximise the difference over a connected subgraph — and this
architecture is that, with the evidence closure applied afterwards and never traded away
for compactness.

## 2. What it is not

**It is not an approximation algorithm with a bound.** PCST is NP-hard; what is
implemented is a greedy growth — start from the best-prized node, attach whichever node
pays for the edge to reach it, stop when nothing pays. The module says this in its first
paragraph, because a module named after PCST and quietly doing something else would make
every comparison against it meaningless.

**Nothing here is learned.** A trained selector would replace the prize function and
nothing else, which is exactly why prizes arrive as an argument: the comparison between
a learned relevance and a ranked one is one substitution, not a second retrieval stack.
Until there is a graph with question-to-evidence pairs to train on, the ranked one is
what runs — and the control this architecture needs in order to be evaluated at all is
itself.

**A selector's score is not evidence strength.** It says a node was worth its context
budget. It says nothing about how well the claim is supported, and nothing in the package
lets it be read as if it did.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core_el` + `scierc`, under `profile: EL`. The selector reads classes for the `whole` rule, and reads them from the classified hierarchy. |
| **Reasoner** | OWL 2 EL classification (`classify`, at the start of the ask chain), so the selector's class tests are complete for the ontology — including the subclasses only a definition makes. Selection itself is optimisation, not inference. |
| **Data** | The store as everywhere else; the selection computed per question. |
| **Components and reuse** | `Adjacency`, the shared `expand` with a supplied adjacency, `Hit.score` as the prize. |
| **Evolution** | A new type appears in the graph and the selector handles it with no retraining, because there is nothing trained. When there is, the frozen-encoder evaluation against the greedy control is the measurement, and the fallback is *between graph methods* — never to text retrieval. |

## 4. The ontology and the engine

The selector takes an n-ary node entire or not at all: a type named under `whole` —
`EvidenceLine`, `Study` — brings its parts with it. That rule is a class test, and a
class test is only as good as the hierarchy it is asked against. With `science_core_el`
the hierarchy is not only what somebody wrote as a parent: `SupportingLine` is *defined*
as an evidence line that supports some proposition, and the EL classifier puts it under
`EvidenceLine` because of that definition. `Schema.is_a` answers from the classified
hierarchy, so the `whole` rule applies to every class the ontology puts under the ones
named, and `classify` at the start of the ask chain records that classification — with
`complete: true` when the EL engine read every axiom, which for an EL ontology it does.

The engine does not touch the selection itself, and nothing it concludes is written down.
Relations named under `parts` and `expand` are widened the same way as everywhere else,
by the relations the ontology puts under them.

## 5. The three rules that matter more than selection quality

### 5.1 An n-ary node is taken whole or not at all

A study relates a method, a dataset, a measure and a number, and it means nothing in
pieces. A selector that kept the method and the number and dropped the dataset has
produced a compact subgraph **asserting something nobody claimed** — the most dangerous
possible output, because it is small, connected and wrong.

Types named in `whole` bring their `parts` relations with them, and are scored with them:
taking such a node means taking its parts, so the prize it offers is the prize of the
whole group.

### 5.2 The evidence closure is not optional

The chosen region goes through the same `expand` as everything else — which means the
objections are pulled in whatever the budget did, exactly as everywhere in this library.
`test_the_closure_is_not_optional_and_keeps_the_objection` selects a region of two nodes
and still finds the opposing position in the package.

### 5.3 When the budget binds, take fewer things with complete grounds

Not more things without them. `trim` drops the lowest-prized **roots** and reselects,
rather than truncating the closure, and reports how many it dropped. A package of ten
results with no evidence is worse than three with it, and a package that quietly answered
a smaller question would be worse still — which is why `selection.trimmed` travels back.

## 6. The algorithm, exactly

```
prizes   = hit.score / max(score)          # normalised, so the edge cost means something
region   = {argmax prize}  ∪  its parts if it may not be split
while |region| < limit:
    for each node in region, for each neighbour not in region:
        attached = neighbour ∪ its parts
        gain     = Σ prize(attached not already in region) − cost
    take the best gain if it is positive, else stop
bundle   = expand(region, ...)             # the shared closure, objections included
while |bundle.nodes| > budget and |roots| > 1:
    drop the lowest-prized root, reselect, count it
```

Determinism: candidates are considered in sorted order and ties resolve on id, so two
runs over one corpus select the same region and a budget cuts it at the same place.

The edge cost defaults to 1.0 against prizes normalised to at most 1: an edge has to be
worth a node of middling relevance, or the region grows to the corpus. A cost of 10 means
nothing is ever attached, which is tested, because a knob that cannot be turned off is
not a knob.

## 7. Competency questions

| Question | What the selection gives |
|---|---|
| What connects these two lines of work? | A compact connected region, rather than two disconnected neighbourhoods |
| Which grounds did the selector leave out? | The difference between the selection and the closed package |
| What survives a strict context budget? | `trim`, with the count of what it dropped |

## 8. Risks and acceptance

- **Greedy, and unbounded in quality.** The first node fixes the region; a graph where
  the interesting connection runs through a low-prized hub is one this will miss. That
  is the case to measure before believing the architecture.
- **Losing a rare objection.** Prevented structurally: objections enter in the closure,
  after selection, so no prize can outbid them.
- **Measuring the wrong thing.** The metric is the quality of the *complete evidence
  package* at a fixed budget, never the selector's own score.

Acceptance: at equal budget, the region must beat a fixed-depth walk on the vague
questions and must never lose an objection. The second is tested; the first needs a
corpus.

## 9. Running it

```bash
atlas run architectures/a16.yaml corpus/*.pdf --store store/
atlas ask architectures/a16.yaml "what connects these two lines of work?" --store store/
```

## 10. Implementation

| Part | Where |
|---|---|
| Vocabulary | `ontologies/science_core_el.ttl`, `ontologies/scierc.ttl` |
| Engine | `atlas/reason/el.py`, `atlas/steps/classify.py`; `Schema.is_a` |
| Selection | `atlas/steps/subgraph.py` (`grow`, `Selection`, `_prizes`) |
| Budget behaviour | `atlas/steps/subgraph.py` (`trim`) |
| Closure | `atlas/steps/graph_expand.py` (`expand`, with a supplied adjacency) |
| Manifest | `architectures/a16.yaml` |
| Tests | `tests/test_subgraph.py`, `tests/test_classify.py` |
