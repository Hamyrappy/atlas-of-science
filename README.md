# Atlas of Science

A substrate for machine-readable markup: a corpus is read once and turned into typed things, each
bound to a verbatim fragment of its source, under whatever ontology you plug in.

How it is put together, in pictures: [`docs/overview.md`](docs/overview.md) ·
Project page: [`index.html`](index.html) · Russian overview: [`docs/initiative.ru.md`](docs/initiative.ru.md)

## Why

A language model reads one paper without any markup at all. Eighty thousand papers of one field
it cannot: they do not fit in a context window, re-reading the corpus for every question costs
more each time it is asked, and every pass returns a slightly different answer.

So the corpus is read once and what is left behind is markup. Statements are lifted out of the
text, typed against an ontology and stored with the fragment they came from. Downstream systems
query that instead of the texts, which makes the expensive pass a fixed cost rather than a
recurring one.

Which classes exist is not the library's business. The core carries six concepts and no domain
vocabulary at all; the classes, fields and relations arrive at run time from an **OWL 2 ontology**,
and the steps that produce them are named in a configuration file rather than wired into the code.
Reading a different field, or reading papers differently, is an ontology and a configuration, not a
fork.

The ontology is not a list of labels. It is reasoned over: an engine for each OWL 2 profile works
out what the axioms imply about what was extracted — every consequence with its derivation, every
contradiction with the two claims behind it — and SHACL checks what a record must carry, in closed
world, where OWL cannot.

A node is worth querying only because it carries the fragment it came from. Every span stores the
exact substring together with the offsets it was taken at, so any statement in the markup can be
checked against the text that produced it, and a text layer that has drifted since ingest is
detectable instead of silently wrong.

```
L4  field map   portfolios of work, drift of topics
L3  topic       a cluster of related sources
L2  source      one document, read once
L1  node        a typed thing, of whichever classes the loaded ontology declares
L0  span        a verbatim fragment of the source
```

No provenance, no node.

## The metamodel

Six concepts, and nothing of any domain:

- **Source** — something that was read. Its text layer is fixed at ingest and hashed.
- **Span** — a verbatim region of a source; its offsets re-slice to the stored text.
- **Node** — a typed thing. The type is a term of the loaded schema; the fields are whatever that
  schema declares.
- **Link** — a typed relation between nodes, itself an object with its own id, fields and evidence.
- **Assertion** — who asserted what, when, on what evidence, and what it supersedes. This is the
  unit of writing: nodes and links are the projection of a history, not rows to be updated.
- **Schema** — the ontology plugged in underneath: its OWL 2 axioms, the classes, fields and
  relations they project, each with an IRI and mappings to public vocabularies, and the class
  hierarchy a reasoner computed from them.

## Install

```bash
pip install "atlas-of-science @ git+https://github.com/Hamyrappy/atlas-of-science.git@main"
```

To work on the library itself, clone it and install in place: `pip install -e ".[dev]"`.

A run talks to a chat-completions endpoint and reads three environment variables: `ATLAS_BASE_URL`
(the base URL of the endpoint), `ATLAS_MODEL` (the model name sent with each request) and
`ATLAS_API_KEY` (the bearer token). Replies are cached under `.atlas-cache/`, or under
`ATLAS_CACHE_DIR` when it is set, so a repeated run over unchanged input makes no requests. Set
`ATLAS_CACHED_ONLY=1` to replay that cache and call nothing: the key is then not required, which is
how a demo runs off a recorded corpus with no account behind it. A reply carries what the provider
counted for it and whether it came from the cache, so a caller can report both.

## Quickstart

```console
$ export ATLAS_BASE_URL=https://api.example.com/v1 ATLAS_MODEL=your-model ATLAS_API_KEY=secret

$ atlas init corpus/
corpus/ontology.ttl
corpus/pipeline.yaml
corpus/questions.yaml
corpus/README.md

$ atlas run corpus/pipeline.yaml paper.pdf
inputs 1	sources 1	renderings 1	statements 41	malformed 0	tokens 51204	cached_replies 0	nodes 33	unplaced 4	needs_review 6	violations 2	assertions 33	store corpus/store	94.318s

$ head -n 1 corpus/store/assertions.jsonl
{"id":"8c5c97324ba55420","agent":{"id":"run:2026-09-13T10:15:00+00:00","kind":"run","label":""},"at":"2026-09-13T10:15:00+00:00","target":{"id":"b3a1c4696f1af143","spans":[{"source_id":"3a750328a5e6","segment":1,"start":0,"end":54,"text":"Our model improves F1 by 3.4 points over the baseline."}],"schema_version":"2775c3049803","type":"Result","fields":{"statement":"Our model improves F1 by 3.4 points over the baseline."}},"supersedes":null,"confidence":null}
```

`init` writes an ontology to fill in (OWL 2 in Turtle, which Protégé opens), a configuration naming
it, a questions file and a note; edit the ontology and the run is about your domain. `run` prints one line: every count the steps it was
configured with left behind — how many statements the model offered, what they were charged, how
many were refused because their quote could not be located, how many landed through a relaxed
search and are worth a look, how many the ontology rejected, and how many assertions were written —
then where the pass was written and what the store recorded it took. The configuration names the
store, and `--store dir` overrides it for one run. The store is append-only, so a second run lands
under what is already recorded rather than replacing it.

`scaffold(directory, templates)` is the same command as a function, and `templates` is a mapping
from a relative name to the text to write there: an application whose corpora have a shape of their
own hands in that shape instead of writing its own `init`.

To read a corpus under the six machine-learning classes this project started with, name the
ontology that holds them. An ontology is looked for beside the configuration that named it, then
under the working directory, then among the ontologies the wheel ships, so a bare name is enough for
that last one. The mapping form also names the OWL 2 profile the ontology must stay within and the
SHACL shapes records are held to:

```yaml
schema: ml_paper        # or a path: ../shared/ontology.ttl

schema:
  ontologies: [science_core_rl, scierc_rl]
  profile: RL
  shapes: [science_core]
```

A legacy YAML pack still loads, into the same OWL layer; `docs/ontology.md` says how.

## Use it as a library

The command line is one caller among several. Everything it does is available as functions, so a
project can take the parts it needs and write the rest itself.

```python
from pathlib import Path

from atlas.model import Agent, Assertion, Node
from atlas.ontology import load
from atlas.steps.ingest_pdf import read_pdf
from atlas.steps.relocate import locate
from atlas.store import open_store

schema = load(Path("ontology.ttl"))
source = read_pdf(Path("paper.pdf"))
store = open_store({"jsonl": {"dir": "store"}})   # or "memory"; a store of your own registers too
store.add_source(source)

match = locate(source, quote, segment)           # a quote becomes a verified span, or None
node = Node(
    id="n1",
    type="Observation",                          # a class your ontology declares, not one of ours
    fields={"summary": quote[:40]},
    spans=(match.span,),
    schema_version=schema.version,
)
assert schema.validate_node(node) == []          # violations, empty when the node fits the ontology

store.assert_(
    Assertion(
        id="a1",
        agent=Agent(id="me", kind="human", label="manual"),
        at="2026-01-01T00:00:00+00:00",          # time is passed in, never read from the clock
        target=node,
    )
)
store.nodes()                                    # the projection: latest non-superseded per id
```

A store is read from request handlers as well as batch jobs, so every read states what it costs:
`sources()` lists what is held, `get_node(id)` and `get_nodes(ids)` fetch without projecting the
whole log, `location` and `artifact(name)` say where the store lives and where a derived file such
as a search index may go (`None` from one that lives nowhere), `add_run`/`runs` record and return
what a pass cost, and `add_schema`/`get_schema` resolve a stored `schema_version` back to the
vocabulary it was written under. `docs/architecture.md` states the complexity of each.

The three layers are independent. `atlas.model` is the metamodel and pulls in nothing else;
`atlas.store` holds the append-only write path; `atlas.steps` are the batteries, each usable on its
own. A project that only wants the provenance guarantees can import `Span`, `Node` and `locate` and
ignore the rest.

To run a whole configured pipeline instead, without the command line:

```python
from atlas.pipeline import Pipeline

pipeline = Pipeline.from_config("pipeline.yaml")
state = pipeline.run(["paper.pdf"], client=client, store=store)
```

A run can be watched while it happens, and it can be entered part-way. `run(..., on_step=...)`
calls back after every step with the name it was configured under, its index, the keys it produced
and the state; `pipeline.initial(inputs, **context)` is the state a run starts from; and
`pipeline.run_state(state)` runs the same configured chain over a state you built yourself — a
question, a store, a client — which is the shape a request has. `pipeline.steps` keeps the
configured name of each step beside its options, and `pipeline.meta` holds every key of the
configuration file other than the five it reserves: `schema`, `store`, `imports`, `steps` and
`ask`.

Registering a step of your own needs no fork: write the function, decorate it with
`@register("my_step", requires=("sources",), produces=("my_key",))`, and name the module under
`imports:` in the configuration so the decorator has run before the name is resolved. The keys it
declares are checked when the configuration is read, so a chain in the wrong order is refused by
the file that holds it rather than by a `KeyError` inside a step.

What a configuration may write under the name is declared the same way, as a model:

```python
from atlas.model import Frozen
from atlas.steps import State, register


class MyStepOptions(Frozen):
    limit: int = 8


@register("my_step", requires=("sources",), produces=("my_key",), options=MyStepOptions)
def my_step(state: State, options: MyStepOptions) -> State:
    return {"my_key": state["sources"][: options.limit]}
```

An option the model does not name, one missing, or one whose value is of the wrong type is refused
while the configuration is being read, naming the file, the step and the fields it does know:

```
atlas: pipeline.yaml: step 'retrieve': unknown option 'treshold'. It takes limit: int = 8
```

A step that takes nothing declares `options=Nothing` (`from atlas.steps import Nothing`), which is
also what a step registered without an `options=` gets, so every step refuses every option it does
not name and none is ever swallowed. The default lives in the model and nowhere else, so the file
and the function cannot disagree about it. `docs/architecture.md` lists what each shipped step
takes.

## Layout

```
atlas/
  model/             the metamodel: source, span, node, link, assertion, schema, and the
                     OWL 2 structural model a schema's axioms are written in
  ontology/          reading ontologies (Turtle, RDF/XML, JSON-LD, legacy YAML packs) into
                     one classified schema, and writing a schema or a store back out as RDF
  reason/            the engines: RDFS and OWL 2 RL over data, EL and a DL tableau over the
                     ontology, QL query rewriting, SHACL, and the profile checker
  text.py            folding, normalising and tokenising, shared by relocation and indexing
  walk.py            one ruling on what a neighbour is, and what a path is
  store/             the append-only log -- in memory, as JSON lines, in SQLite -- and the
                     projections over it
  steps/             ingest, extraction, relocation, relation, validation (by schema and by
                     SHACL), critique and repair, induction, reasoning, recording, indexing,
                     seven ways of selecting an evidence package, answering
  catalogue.py       the architectures on offer, read off their manifests
  pipeline.py        a configuration of step names run in order over one dict of state
  scaffold.py        the project skeleton `atlas init` writes
  llm.py             the chat client, with a disk cache in front of it
  cli.py             run, ask, init and variants
architectures/       one manifest per architecture: the ontologies and their profile, the
                     chain that builds, the chain that answers, and why anyone would choose it
ontologies/          OWL 2 in Turtle, shipped in the wheel (`atlas.ontology.builtin(name)`)
  science_core*.ttl  the argument: claim, position, line of evidence, result, conditions,
                     computation, with BFO, IAO, OBI, ECO, SIO and EVI identities; a base
                     module and one module per profile (rl, el, ql, dl)
  process*.ttl       plan against run, conditions, positive and negative results
  science_map*.ttl   the topic layer, which is deliberately not a taxonomy
  semantic_units.ttl the form of a claim: kind, quantifier, polarity, modality, terms
  scierc*.ttl        a local versioned profile of the SciERC annotation scheme
  ml_paper.ttl       one domain's ontology: six classes and eight relations, to copy
  fields.ttl         the datatype properties every class lists as its fields
  atlas.ttl          the substrate's own vocabulary; never part of a schema
  shapes/            SHACL: what a record must carry, in closed world
  README.md          the modules, the profiles, and how to write one
pipeline.yaml        the default run, over `ml_paper`
tests/               the suite; no network, no API key, no committed binaries
docs/
  overview.md        how the whole thing fits together, in six diagrams
  architecture.md    the metamodel, the step model, the store, the open questions
  architectures/     one specification per architecture, and the rule they all obey
  ontology.md        what an ontology holds, how it is loaded, which engine reads which
                     part of it, what SHACL checks, how the version is hashed
  evaluation.md      the measurement contract: competency questions, seams, negative controls
  initiative.ru.md   the Russian write-up of the initiative
CLAUDE.md            how to work in this repository: invariants, layout, direction
HANDOFF.md           what the work stands at, and the bar the next agent has to meet
index.html           the project page
```

## Design

- Nothing under `atlas/` names a class, a field or a relation of any domain. `tests/test_substrate.py`
  runs the shipped steps over an invented ontology and holds that claim to it.
- Only the engines that cannot invent an individual -- RDFS and OWL 2 RL -- run over extracted
  data, and every fact they derive carries its derivation and the spans of its premises. EL and DL
  are asked about the ontology; QL answers a query by rewriting it. None of them materialises
  anything a source did not say.
- A step is a function from the run's state to the keys it adds, registered under a name. Replacing
  one is naming a different one in the configuration file.
- A type that crosses a step boundary lives with the step that defines it, and importing it from
  another step is normal. `atlas/model/` holds only what a store persists and every run exchanges.
- Writing is asserting: a store is an append-only log, and the graph is the projection of it. A
  correction supersedes; nothing is overwritten.
- The model is asked for a verbatim quote and never for character offsets, which it would invent;
  offsets are recovered by searching the segment text.

## Architectures

An architecture here is a configuration, not a mode or a class: a manifest under
`architectures/` naming the ontologies it loads and the OWL 2 profile they stay within, the
chain that builds the graph, the chain that
answers over it, and the options each step runs under. Nothing in `atlas/` branches on which one
is in use.

```bash
atlas variants                    # what is on offer
atlas variants a18 --json         # one of them, as an interface reads it
atlas run architectures/a05.yaml corpus/*.pdf --store store/
atlas ask architectures/a05.yaml "under which conditions does this hold?" --store store/
```

Fifteen ship. They differ in three places — what is stored about a claim (5, 8, 12, 13, 14), how
the vocabulary and the graph come to exist (4, 6, 10, 15), and how the evidence package is
selected (0, 7, 16, 18, 19, 20) — and they share everything else, which is what makes them
comparable. Each has a specification in `docs/architectures/` with the same eleven sections.

**The rule they all obey: an answer is built from a walked graph.** Ranking finds where to start;
it does not find an answer. Every `ask` chain builds a `Bundle` and answers from one, an objection
survives a budget that everything else loses to, and a package that walked nothing is reported as
a gap rather than handed to a model. `tests/test_catalogue.py` checks that over every manifest.

## Status

Working today: the metamodel and its projections; OWL 2 ontologies in Turtle with a module per
profile, loaded, merged, classified and held to a profile; engines for RDFS, OWL 2 RL (with the
derivation of every consequence and every clash), EL classification, QL query rewriting into SQL,
and an OWL 2 DL tableau; SHACL validation in closed world; legacy YAML packs imported into the same
layer; an append-only store in memory, as JSON lines, and
in SQLite with the graph reads pushed into recursive queries; ingest for PDF, plain text, markdown
and delimited tables; extraction of typed statements and of relations, each bound to a quote the
library places itself; deterministic critics with a bounded repair and a quarantine; induction of
what the ontology has no word for, with a gate that produces a proposal and never an edit; a formal
gate over the schema; materialised entailment with the derivation of every consequence; seven ways
of selecting an evidence package, and an answering step whose uncited lines are dropped and whose
ungrounded packages are refused; the cached model client; `run`, `ask`, `init` and `variants`.

Not implemented yet: canonicalisation of nodes across sources; the evaluation harness, whose
contract is written in `docs/evaluation.md` and whose code does not exist; a store in PostgreSQL.
The shipped ranking is term overlap with a length normalisation and nothing else — enough to
answer from hundreds of documents, and honest about missing a question phrased in words the text
avoids. Nothing here has been run over a corpus large enough to rank the architectures against
each other, and the scores in their manifests say so wherever they appear.

## Licence

Code is MIT, in `LICENSE`. Texts and diagrams are CC BY 4.0.
