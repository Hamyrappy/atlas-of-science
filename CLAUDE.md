# Working in this repository

Atlas of Science is a substrate for machine-readable markup: a small metamodel that carries no domain vocabulary, an ontology plugged in under it as data, and a pipeline of replaceable steps that turns sources into typed things bound to verbatim fragments of the text. This file is for coding agents and for the people directing them. It states what must not break, where things go, and how the work is divided.

## Read in this order

1. `README.md` — what the library does and how to run it.
2. `docs/overview.md` — the same thing in six diagrams: the two chains, the six concepts, the
   four invariants, what a step is. Fifteen minutes, and the rest of this file will make sense.
3. `HANDOFF.md` — where the work stands, the bar the code is held to, and the traps already paid for.
4. `docs/architecture.md` — the metamodel, the step model, the store, provenance end to end.
5. `atlas/model/` — the six types everything else exchanges. Read the files themselves; nothing here restates them.

Then the module you are about to change, and its tests. Do not start from a grep.

## The four invariants

Break any of these and the markup stops being worth more than the text it came from.

1. **No provenance, no node.** `Evidenced.spans` has `min_length=1`, and a span is cut out of a source through `Span.of`, which takes the text from the segment rather than being told it, so offsets and quote cannot disagree. A statement whose quote cannot be located is dropped and counted, never stored.
2. **The text layer is frozen at ingest.** `Source.segments[i].text` is the sole coordinate system for every span that will ever point into that source. Never normalise, strip or reflow it after ingest. `Source.text_hash` names the text layer and is checked when a rendering is read back; an edited rendering is refused.
3. **Every object names the schema it was written under.** `schema_version` is the content hash of the packs that were loaded. A node written last month must stay interpretable after today's edit to the pack.
4. **Writing is asserting.** Nothing in a store is updated or deleted. A correction is a new `Assertion` naming the one it supersedes, and the graph is the projection `current` makes over that history — which is what lets a re-extraction land under a human judgement instead of erasing it.

The model is asked for a verbatim quote and never for character offsets, which it would invent. Recovering offsets is `atlas/steps/relocate.py` and nowhere else.

## The metamodel is six concepts and no domain content

`Source` was read; `Span` is a verbatim region of it; `Node` is a typed thing and `Link` a typed relation, both valid only under the `Schema` they name; `Assertion` says who claimed one of those, when, on what evidence and what it replaces; `Schema` is the ontology, loaded from packs at run time.

Nothing under `atlas/` may name a type, a field or a predicate of any domain. The six types that used to be built in now live in `packs/ml_paper.yaml`, which is one domain's pack and is loaded only when a configuration names it. `tests/test_substrate.py` is the standing proof: it runs the shipped steps over an invented vocabulary, and a change under `atlas/` needed to make it pass means a domain has leaked into the core.

## Layout and what belongs where

```
atlas/model/           the metamodel: source, graph, assertion, schema; no IO, no vocabulary
atlas/ontology/        reading packs off disk and merging them into one Schema
atlas/store/           the append-only write path and the projections read back out of it
atlas/steps/           one module per replaceable step, each registered under a name
atlas/pipeline.py      a configuration of step names run in order over one dict of state
atlas/text.py          folding, normalising and tokenising; one ruling on what a dash is
atlas/walk.py          one ruling on what a neighbour is and what a path is; no vocabulary
atlas/catalogue.py     the architectures on offer, read off their manifests
atlas/scaffold.py      the project skeleton `atlas init` writes
atlas/llm.py           one chat client with a disk cache in front of it
atlas/cli.py           argument parsing and file IO; no logic lives here
packs/                 ontology packs; data the wheel ships, reached through `ontology.builtin`
architectures/         one manifest per architecture, reached through `catalogue.variants`
docs/                  overview in diagrams, architecture, ontology, evaluation contract, one spec per architecture
tests/                 one file per module; fixtures are generated, never committed as binaries
```

A step is a function from the state of a run plus its configured options to the keys it adds to that state. It does not know about a database, a web server or a queue: the store is handed to it. Storage and IO live at the edge.

**An architecture is a configuration and never a branch.** A manifest under `architectures/` names the packs, the chain that builds (`steps`) and the chain that answers (`ask`), plus a `variant:` block saying why anyone would choose it. Nothing under `atlas/` branches on which architecture is in use — by the time anything runs there is only a pipeline, and that is what makes fifteen of them maintainable. Adding one is a manifest, a specification under `docs/architectures/`, and whichever step it needs that does not exist yet. `atlas variants` and `atlas.catalogue` are the seam an interface is built on.

Adding a step: write the function in its own module under `atlas/steps/`, decorate it with `@register("name", requires=(...), produces=(...), options=NameOptions)` naming the state keys it reads and adds and the `Frozen` model of what a configuration may write under the name — `options=Nothing`, which is also the default, if it takes nothing — import the module in `atlas/steps/__init__.py`, add `tests/test_<step>.py`. Nothing else changes, and a configuration that does not name it does not run it. The options model is where that step's defaults live, so a default is never written twice; an option no model names is refused when the configuration is read. A step outside this tree is named under `imports:` in the configuration instead of being imported here.

A type that crosses a step boundary lives **with the step that defines it**, and importing it from another step is normal — `Statement` in `relocate.py`, `Hit` in `retrieve.py`. `atlas/model/` holds only what the substrate is made of: what a store persists and what every run exchanges whichever steps are configured. The test is mechanical: is it asserted, does it carry a `schema_version`, does it outlive the state dict? `Run` answers yes to the first and is in `atlas/model/`; `Hit` answers no to all three. The other rule — everything inter-step into the metamodel — would pull every future step's intermediate into the six concepts, which is what this section exists to prevent.

## Commands

```bash
pip install -e ".[dev]"    # once
pytest                     # the whole suite, no network, no API key
ruff check .               # what CI runs
atlas init corpus/                                          # pack, configuration, questions, README
atlas run pipeline.yaml paper.pdf --store store/            # a configured run into a store
```

Tests never reach the network and never need a key. A test that would call a model uses the stub step in `tests/conftest.py`, which has the signature of any other step.

## Changing the metamodel

`atlas/model/` is what everyone depends on; a pack is what nobody should have to change to describe a new domain.

- Adding a field to a model is free. Renaming or removing one is a breaking change for every step and for every object already written.
- A pack is byte-hashed into `Schema.version`, so editing one changes the version of every future run and invalidates the prompt cache. Domain vocabulary goes into a pack, never into the metamodel.
- Both are changed with the other people on the project knowing, not in passing.

## Documentation is part of the change

Six documents carry this project, and each has one job. Keep them true; a claim that has quietly
stopped holding is worse than no claim, because it is trusted.

- `README.md` — what the library is, how to install it, how to run it from the command line, how to
  import it. Every command and every code sample in it must run as written.
- `CLAUDE.md` — this file: the invariants, the layout, the rules for changing the metamodel, the
  direction. It changes when a rule changes, not when code moves.
- `docs/overview.md` — the whole library in six diagrams, for somebody who has just been handed
  the repository. It says nothing the other documents do not; it says it in fifteen minutes.
- `docs/architecture.md` — the metamodel, the step model, the store, provenance end to end, and the
  open questions. The reference a contributor reads before touching anything.
- `docs/ontology.md` and `docs/evaluation.md` — how a pack is written, and what is measured where.
- `HANDOFF.md` — for whoever continues this: where the work stands, the standard the code is held
  to with the examples that show it, how to add the next architecture, and the traps already paid
  for. It changes when the state of the work changes, which is most commits that add a step.
- `docs/architectures/` — one specification per architecture, eleven sections each so two can be
  read side by side, plus the rule they all obey.

The rule: **a change that alters behaviour updates its document in the same commit.** New public
function, new step, new configuration key, a renamed field, a changed invariant, a command whose
output looks different — all of them land with their documentation, not after it. If that feels
like too much writing for the change, the change is probably bigger than it looked.

Two habits that keep this honest: copy command output into the documentation from a real run rather
than typing what it should say, and when a document states something is not implemented, delete
that sentence on the commit that implements it. Anything you had to work out by reading the source
is a gap in the documentation — write it down where the next person will look, not in a commit
message.

## Where this is going

Direction, so that today's code leaves room for it rather than being redone:

- **Identity.** Every type, predicate and domain term carries an IRI and mappings to public vocabularies. This is the one thing that cannot be retrofitted cheaply: a label is not an identity. The loader enforces it on any pack that declares prefixes.
- **Schema artifacts.** The pack is authored once and SHACL, OWL and JSON Schema are generated from it. SHACL validates nodes; a reasoner runs in CI over the schema only, never over extracted data, where an open-world inference would invent the missing spans it is supposed to reject.
- **Storage.** A third store, in PostgreSQL: JSONB for fields that are still moving, full text and vectors in the same engine, and the projections of `atlas/store/__init__.py` pushed into queries. RDF and a SPARQL endpoint are a published projection of it, not the working store.
- **Steps not yet written.** Canonicalisation of nodes across sources; an evaluation harness driven by competency questions with a dev/test split and corrupted negative controls that must drop the metric. Text ranking still ships in its mechanical form only — one inverted index and term overlap — so hybrid ranking is still ahead. It goes in as a step of its own, named in a configuration in place of `retrieve`, reusing the public `Index` and `overlap`; the seam is the step registry and there is deliberately no second one inside the step.

## The rule every architecture obeys

**An answer is built from a walked graph, not a list.** Ranking finds where to start; it does not find an answer. Every `ask` chain contains a step producing a `Bundle` and ends in one consuming it; a package that walked nothing is reported as a gap and never handed to a model; and a relation named under `opposes` is pulled into the package after the walk, whatever the budget did. `tests/test_catalogue.py` checks all three over every manifest, which is the only way a rule stated in a document stays true.

## What not to do

- Do not weaken an invariant to make a test pass. The invariant is the product.
- Do not let an architecture become a branch under `atlas/`. It is a manifest.
- Do not present an inference, a diffusion score or a cluster as evidence. A derived relation says which rule produced it; a topic says it is not a class; a selector's score says a node was worth its context budget and nothing more.
- Do not name a domain type, field or predicate anywhere under `atlas/`.
- Do not add a database, a server or a queue inside a step.
- Do not ask the model for offsets, segment numbers as ground truth, or anything you can verify yourself.
- Do not overwrite or delete what a store holds; supersede it.
- Do not commit binary fixtures, a cache directory, a virtualenv, or anything under `.atlas-cache/`.
- Do not report a metric without the cases behind it. A number that survives a corrupted input is worthless.
