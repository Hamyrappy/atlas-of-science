# Architecture 19 — Explanatory paths with a preserved counter-path

| | |
|---|---|
| **Id** | `a19` |
| **Manifest** | [`architectures/a19.yaml`](../../architectures/a19.yaml) |
| **Family** | Path selection |
| **Optimises** | A compact explanation, without becoming more confident by being compact |
| **Score** | relevance 90, novelty 89, prospect 91, **total 90** — an engineering judgement, not a measurement |

## 1. What it is for

A graph search that returns everything within two hops returns thirty restatements of
one result and buries the chain a reader actually wanted. What explains a connection is
an **ordered path** — this method was used for that task, evaluated by that measure,
which produced that number — and a handful of those is worth more than a neighbourhood.

So: enumerate the bounded simple chains between the things the question named, score
them by a flow that decays with each hop, prune, and then close over the evidence as
everywhere.

## 2. What it is not

The flow model is a decay per hop times the weight of each relation crossed. It is
monotone in length and in weight, and it is **not** PathRAG's published algorithm; the
module says so where it is defined. The part of this architecture that matters is not
the scoring — it is what may be thrown away.

It also does not chain across an n-ary node as if it were a pair. Paths are kept whole
and the closure adds each node's context, so a chain crossing an evaluation brings that
evaluation's conditions with it rather than silently joining participants of two
different experiments.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core_rl` + `scierc_rl`, under `profile: RL`. Relations carry the meaning a path is made of, including the ones the ontology derives. |
| **Reasoner** | OWL 2 RL (`entail`) over the stored graph before enumeration; a path may cross a derived relation, which the package marks with its rule. Enumeration and pruning are not inference. |
| **Data** | The store; the paths computed per question and returned with the package. |
| **Components and reuse** | `walks` for enumeration, `weights` for the flow, the shared `expand`. |
| **Evolution** | A search that keeps failing on a missing relation is a proposal with its evidence. **Path popularity is never grounds for an axiom**, and a new relation type is admitted to path templates only after it is released. |

## 4. The ontology and the engine

An explanation is an ordered chain, and some of the most useful chains are ones nobody
wrote in one piece. `entail` runs the OWL 2 RL rules before `select_paths`, and the paths
are enumerated over the stored links and the derived ones together: `computed_from_data`
is a single step from a result to the dataset behind it where the text only said the result
came from a computation that used the dataset; an inverse is read forwards; a chain of
`part_of` is one hop.

That makes paths shorter and the scoring kinder to them, which is exactly why a derived
step has to stay visible. Every derived link a kept path crosses is marked in the package
as inference, with its derivation — the rule, the premises it rests on, their spans — and
the premises are in the package too, so an explanation that leans on the ontology can be
unfolded back into what the sources said. The counter-path rule is unchanged, and a
relation the ontology puts under a named opposing one counts as opposing.

## 5. The two rules that decide whether pruning is safe

### 5.1 Redundancy is judged by content, not by text

Two paths crossing the same relations between the same things are one path however
differently they read; two paths with the same shape over different studies are two.

```
signature = (node, predicate, node, predicate, node, …)
```

That is what *"the same explanation"* actually means here, and it is why deduplication
happens on the signature rather than on a rendered string.

### 5.2 A counter-path is never pruned

A path crossing a relation the configuration names as opposing is kept **whatever it
scored**.

This is the rule the module exists to state. Pruning optimises for the chain that
explains the connection; the chain that argues against it is rare by nature and scores
badly by construction. Losing it would make a pruned search *systematically more
confident* than an unpruned one — the exact opposite of what a smaller context is
supposed to buy.

The order is deliberate: deduplicate, then take the best to budget, then put back the
counter-paths the budget dropped — each carrying the reason it survived
(`flow 0.1000, kept as a counter-path`), so a reader can tell it was kept on purpose
rather than by luck.

## 6. The algorithm, exactly

```
graph   = stored links ∪ what `entail` derived
roots   = the ranked nodes
paths   = for every pair of roots: simple walks up to `depth`, at most `candidates`
score   = Π weight(edge) · decay,  per hop        # monotone in length and in weight
prune   = dedupe by signature
        → keep the best `keep`
        → restore every counter-path that was dropped
bundle  = expand(the nodes of the kept paths)      # the shared closure
```

Enumeration is exponential in depth and is bounded by `candidates` rather than by
cleverness, which is stated rather than hidden. Determinism comes from `walks`, which
orders neighbours by link id.

## 7. Competency questions

| Question | What paths give |
|---|---|
| What chain explains the link between these two results? | A small ordered set, not a neighbourhood |
| Which transitions are about the subject matter? | The predicate of each hop, in the path |
| What survives a strict context limit? | Measurable redundancy reduction with the evidence intact |

## 8. Risks and acceptance

- **Losing the rare counter-path** is the risk, and §5.2 is the answer. It is tested by
  pruning to a budget of one and asserting that two paths come back.
- **A short path is not a proof.** A chain from a method to a better number does not say
  the method is better; the relation types are printed at every hop precisely so that an
  answer cannot pretend otherwise.
- **Popularity is not an axiom.** A path everybody's questions traverse is a path, and
  the route from there to a schema change runs through the ordinary proposal gate.

## 9. Running it

```bash
atlas run architectures/a19.yaml corpus/*.pdf --store store/
atlas ask architectures/a19.yaml "what chain explains the link between these two?" --store store/
```

## 10. Implementation

| Part | Where |
|---|---|
| Vocabulary | `ontologies/science_core_rl.ttl`, `ontologies/scierc_rl.ttl` |
| Engine | `atlas/reason/rl.py`, `atlas/steps/entail.py` (`entail`, `mark`) |
| Enumeration and scoring | `atlas/steps/paths.py` (`enumerate_paths`, `flow`, `Path.signature`) |
| Pruning and the counter-path rule | `atlas/steps/paths.py` (`prune`) |
| Closure | `atlas/steps/graph_expand.py` (`expand`) |
| Manifest | `architectures/a19.yaml` |
| Tests | `tests/test_paths.py` |
