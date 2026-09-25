# Architecture 13 — Federation of registries

| | |
|---|---|
| **Id** | `a13` |
| **Manifest** | [`architectures/a13.yaml`](../../architectures/a13.yaml) |
| **Family** | Federated traversal |
| **Optimises** | Not manufacturing consensus out of the topology of who republished what |
| **Score** | relevance 78, novelty 93, prospect 93, **total 87** — an engineering judgement, not a measurement |

## 1. What it is for

A laboratory, a group or a project runs its own Atlas and publishes what it found.
Several of them together are worth more than any one — and only if two things are got
right, because each of them is a way a federation quietly becomes worthless:

1. **Nothing is taken on trust.** A record that arrives is checked against the source it
   claims to come from.
2. **Two publishers are not two confirmations when they read the same paper.** This is
   *the* error a federation exists to make, and it has to be built not to make it.

## 2. What it is not

It is not a distributed query. Questions are answered over a **local snapshot** built
from what passed the checks, so one answer is about one state of the world; a live
fan-out would mix snapshots inside a single answer and make it unreproducible.

It is also not useful for one corpus with one owner. The honest note in the manifest
says so: the machinery earns its place once there are several publishers who do not
share a schema release, and not before.

## 3. The five questions

| | |
|---|---|
| **Schema** | A shared ontology — `science_core_rl` + `scierc_rl` here — that publishers agree on, under `profile: RL`. Independent modules are what `versions` is for. |
| **Reasoner** | OWL 2 RL over the snapshot (`entail` with `identity: [same_as]`), for one thing above all: which nodes are one individual. What `federate` and `count_independence` compute on top of that — integrity and independence — is arithmetic. |
| **Data** | Each registry's own store, read; one local snapshot, built. The snapshot is a store like any other, so everything downstream is unchanged. |
| **Components and reuse** | `Span.covers` for the integrity check; `open_store` for reading any registry the library can open; the shared `Bundle`. |
| **Evolution** | A publisher moves to a new vocabulary and its records are **held** until somebody maps it. Connecting a new registry is a snapshot diff: new paths, new evidence, new conflicts. |

## 4. What `federate` checks

Three questions per record, in the order that decides what to do about a failure:

| Check | Why it is in this order |
|---|---|
| Was the **source published with it**? | Without the source there is nothing to verify against, and the record is unusable whatever else is true |
| Does every span **still cut its own text** out of that source? | This is the same rule the library applies to its own extraction, applied to somebody else's — and it is nearly free, because `Span.covers` already exists |
| Is it under a vocabulary **this Atlas can read**? | A mapping problem, not an integrity problem, and it is *held* rather than dropped |

The last distinction matters. A record written under an unmapped vocabulary is not
wrong; it is waiting for somebody to publish the mapping. `held` carries the registry,
the assertion, the target and the reason, so a sync can be re-run once the mapping
exists and nothing has to be re-published.

## 5. Counting confirmations

```python
counted = independence(bundle.nodes, origins)
counted.independent   # distinct sources behind the claims -- the honest number
counted.registries    # how many registries published them -- never the same thing
counted.republished   # the sources that arrived from more than one registry
```

Three registries republishing one study is **one** study. A federation that counted it
three times would manufacture consensus out of its own topology, which is precisely what
makes a federated evidence base worse than a single one rather than better.

Both numbers come back, and `republished` names the sources that arrived twice, so the
gap between them can be explained rather than argued about. `count_independence` runs it
over the evidence package, so the number an answer would quote is the number about what
that answer actually rests on.

## 6. Identity, and the engine that decides it

Registries mint their own ids. One study published by two of them arrives as two nodes,
and counting over nodes would count it twice — the same error as counting over
publishers, one level down. Deciding that two records are one individual is what
`owl:sameAs` means, and OWL 2 RL is the profile that can execute it over data: `eq-sym`,
`eq-trans` and `eq-rep` make every fact about one a fact about the other, and `prp-fp` /
`prp-ifp` derive an identity from a relation the ontology makes functional.

`science_core_rl` declares `same_as` — symmetric, transitive, with `skos:closeMatch
owl:sameAs` — and the manifest runs `entail: {identity: [same_as]}`, which gives it the
meaning of `owl:sameAs` for this run and no other. Each identity the engine derives comes
back in `identities`, with the rule and the premise, and `count_independence` reads them:

```python
counted.sources       # distinct sources behind the claims -- the honest number
counted.individuals   # distinct things the claims are about, once identities are applied
counted.identified    # the pairs the ontology made one, inside this package
```

Sources are still counted as sources. Two papers reporting one study are two independent
reports of it, which is what a confirmation is; one study under two registry ids is one
study, which is what `individuals` says. A `same_as` link is itself a claim with a span —
somebody said the two records are one — so an identity is as retractable as anything
else, and `supported` recomputes what still follows when it is withdrawn.

## 7. Pipeline

### 7.1 Build (at each node of the federation)

```
ingest_pdf → extract_llm → relocate → validate → relate_llm → relate → assert → index_nodes
```

Ordinary. A publisher is just an Atlas; what makes it a federation member is that
somebody else reads its store.

### 7.2 Ask (at the Atlas doing the federating)

```
federate → index_nodes → retrieve → entail{identity: same_as} → graph_expand_entailed
         → count_independence → graph_answer
```

`federate` runs first and produces the `store` everything downstream uses — so the
snapshot is built, indexed and answered over in one chain, and the answer is about one
state of the federation.

## 8. Evolution

**A publisher changes vocabulary.** Its new records are held, named, and waiting. The
local Atlas does not rewrite their IRIs and does not guess a mapping: a class split into
two cannot be reassigned by name, and the records stay on the old release, visibly
needing work.

**A new registry is connected.** The interesting output is the diff: which paths in the
graph are new, which evidence is new, and which conflicts are new. A conflict that
appears on connecting a registry is a finding, and `reconcile` (architecture 6) is what
classifies it.

## 9. Competency questions

| Question | What the federation gives |
|---|---|
| Which groups independently confirm this? | `independence`, counted over sources |
| Which disagreements are terminological? | Records held for an unmapped vocabulary, beside conflicts that survive mapping |
| What changed when a registry was connected? | A snapshot diff: new nodes, new links, new conflicts |

## 10. Risks and acceptance

- **Version heterogeneity is the normal state**, not an exception. `versions` and the
  held queue are the machinery for it; a federation that accepted everything would be
  merging records that do not mean the same thing.
- **The same wording from two registries is not the same claim.** A trusty hash protects
  a record; it says nothing about whether two records are about one proposition, which
  is a separate question this architecture does not answer.
- **For one owner and one corpus, this buys nothing** and costs a sync. The manifest
  says so in `cost`.

Acceptance: a test with two registries reading the same paper must report **one**
independent confirmation and two registries. That is `test_three_registries_reading_one_paper_are_one_confirmation`.

## 11. Running it

Point the manifest at the registries — store specifications exactly as a configuration
names its own store:

```yaml
ask:
  - federate:
      registries:
        lab-a: {jsonl: {dir: ../lab-a/store}}
        lab-b: {jsonl: {dir: ../lab-b/store}}
      versions: [978e0ba714bf]
```

```bash
atlas ask architectures/a13.yaml "who independently confirms this?" --store store/
```

## 12. Implementation

| Part | Where |
|---|---|
| Syncing and checking | `atlas/steps/federate.py` (`federate`, `check`, `Held`) |
| Counting confirmations | `atlas/steps/federate.py` (`independence`, `Counted`, `count_independence`) |
| Identity | `ontologies/science_core_rl.ttl` (`same_as`); `atlas/reason/rl.py` (the equality rules); `atlas/steps/entail.py` (`Identity`) |
| The integrity rule | `atlas/model/source.py` (`Span.covers`) |
| Manifest | `architectures/a13.yaml` |
| Tests | `tests/test_federate.py` (two ids made one individual), `tests/test_rl.py` |
