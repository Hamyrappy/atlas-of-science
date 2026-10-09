# Architecture 18 — Associative graph memory

| | |
|---|---|
| **Id** | `a18` |
| **Manifest** | [`architectures/a18.yaml`](../../architectures/a18.yaml) |
| **Family** | Associative diffusion |
| **Optimises** | A question with no pattern, where several indirect routes are the evidence |
| **Score** | relevance 86, novelty 88, prospect 88, **total 87** — an engineering judgement, not a measurement |

## 1. What it is for

*"Which work connects these two ideas?"* names two things and nothing about how they
might be related. A fixed walk from either of them finds what is near it, not what
connects them, and a pattern query needs a pattern nobody has.

Diffusion answers that shape. Start a random walk at the nodes the question named, let
it wander with a chance of restarting, and see where it spends its time. A node
reachable by several indirect routes accumulates weight that no single path would have
given it, and that accumulation *is* the signal: being connected three weak ways is
different from being connected one weak way, and only a diffusion sees the difference.

## 2. What it is not

The result is a ranking of **places to look**. It is not a measure of truth, it is not a
measure of support, and the architecture is built so that it cannot be mistaken for
either.

It is also not a return to schemaless retrieval. The typed graph, the vocabulary, the
positions and the evidence closure are all unchanged; the diffusion is a way of choosing
roots, and everything after it is the shared machinery.

## 3. The five questions

| | |
|---|---|
| **Schema** | `science_core_rl` + `scierc_rl`, under `profile: RL`. The diffusion reads the graph as the ontology makes it. |
| **Reasoner** | OWL 2 RL (`entail`) over the stored graph before the diffusion; derived links are walked, and marked as inference in the package. Personalised PageRank itself is arithmetic over an adjacency matrix. |
| **Data** | The store; the ranking computed per question, asserted never. |
| **Components and reuse** | `Adjacency`, `weights`, `walks` for the connecting routes, the shared `expand`. |
| **Evolution** | A new relation type has to be admitted to the diffusion deliberately — not every scientifically correct relation is useful to spread through, and a very general one makes a hub dominate. That is a weight, not a schema change. |

## 4. The ontology and the engine

A diffusion spreads relevance over whatever graph it is given, and the graph it is given
here is the one the ontology makes: `entail` runs the OWL 2 RL rules before `diffuse`,
and the adjacency the power iteration runs over is the stored links plus the derived ones
— a transitive `part_of` collapsed into one step, `has_part` read as `part_of` backwards,
`computed_from_data` joining a result to the dataset its computation used. Two things
follow. A study reachable only through a chain nobody asserted in one piece is reachable;
and every derived edge a route crosses is marked in the package, with the rule that
licensed it, so *"the graph connected them"* is visibly different again from *"the
ontology connected them"*, and both from *"a source said so"*.

What is followed is widened too: a relation named in the options brings every relation
the ontology makes a kind of it. The weights per relation are still the control for hub
bias, and a derived relation gets the weight of its name like any other.

## 5. The three rules

### 5.1 Direction does not become weight

A relation that means support and one that means dispute both carry the weight their
predicate was given. This is not a simplification: **a diffusion needs non-negative
weights**, and a negative weight is not a smaller positive one — it is a request to spend
negative time somewhere, which is not a thing.

So which side a relation is on stays where it belongs: in the graph, applied by the
evidence closure afterwards. The consequence is worth stating plainly, because it is the
right one: *a heavily visited claim can turn out to be the disputed one*. That happens,
and this arrangement makes it visible rather than impossible.

### 5.2 A score comes back with the walk that explains it

Every ranked node carries the shortest walk from a seed, or nothing. A node with a high
score and no walk to show for it is a **hub**, not a finding, and the walks are what let
a reader tell the difference — the package says so in as many words:
`diffusion 0.0116, with no route from a seed`.

### 5.3 Hubs are the failure mode

A relation meaning almost nothing — *"mentioned in the same paper"* — makes every
well-connected node rank highly for every question. Per-predicate `weights` are the
control and `follow` is the blunter one. The honest way to use either is to look at the
walks and see what the ranking was actually made of; no threshold fixes this.

## 6. The algorithm, exactly

```
graph   = stored links ∪ what `entail` derived      # the graph as the ontology makes it
seeds   = normalise(hit.score)                     # where the question said to begin
scores  = seeds
repeat `rounds` times:
    for each node:
        out = Σ weight(edge) over its edges, both directions
        if out == 0: return its weight to the seeds      # keeps the total at one
        else: push weight along each edge in proportion
    scores = (1 − damping) · seeds + damping · spread
rank    → take `limit` → find the shortest walk from a seed to each
        → expand(): the shared closure, objections pulled in whatever the budget did
        → mark(): which links nobody claimed, what each node was inferred to be
```

`damping` is 0.85, which is where this family of algorithms conventionally starts. It is
a pilot value to be measured and not a claim about any published system's tuning, and
the module says so where the constant is defined. `rounds` is a cap rather than a
convergence criterion, and also says so.

## 7. Competency questions

| Question | What the diffusion gives |
|---|---|
| Which work connects these two ideas? | Nodes reachable by several indirect routes, which no single walk ranks |
| Through which concepts was this found? | The connecting walk on every ranked node |
| Was this a hub rather than the science? | A high score with no route, or one route through a general relation |

## 8. Evolution

A term means something different in a new area. Repeated extraction and grounding errors
produce a separate candidate; a shared label does **not** merge them (that is
architecture 4's gate, and it applies here unchanged). After a promotion only the
affected nodes and edges are rebuilt, and the ranking for a question is computed against
the new adjacency.

When a new relation type appears, admitting it to the diffusion is tested separately.
Not every scientifically correct relation is useful to spread through: too general an
edge makes a hub dominate every question, and that is a weight to set, not an axiom to
add.

## 9. Risks and acceptance

- **Hub bias**, above. The first thing to look at, always.
- **Association is not evidence.** Structural: the closure is what supplies evidence, and
  a diffusion score never enters a package as support.
- **Rare objections.** Protected by the same closure rule as everywhere: an objection is
  pulled in whatever the budget did.

Acceptance: the diffusion must reach a node that a two-hop walk from the same seed does
not, and the package must still hold both sides. Both are tested.

## 10. Running it

```bash
atlas run architectures/a18.yaml corpus/*.pdf --store store/
atlas ask architectures/a18.yaml "which work connects these two ideas?" --store store/
```

## 11. Implementation

| Part | Where |
|---|---|
| Vocabulary | `ontologies/science_core_rl.ttl`, `ontologies/scierc_rl.ttl` |
| Engine | `atlas/reason/rl.py`, `atlas/steps/entail.py` (`entail`, `mark`) |
| The diffusion | `atlas/steps/diffuse.py` (`pagerank`, `diffuse`, `Ranked`) |
| Weights per relation | `atlas/walk.py` (`weights`) |
| Connecting routes | `atlas/walk.py` (`walks`) |
| Manifest | `architectures/a18.yaml` |
| Tests | `tests/test_diffuse.py` |
