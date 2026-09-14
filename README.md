# Atlas of Science

A substrate for machine-readable markup: a corpus is read once and turned into typed things, each
bound to a verbatim fragment of its source, under whatever ontology you plug in.

Project page: [`index.html`](index.html) · Russian overview: [`docs/initiative.ru.md`](docs/initiative.ru.md)

## Why

A language model reads one paper without any markup at all. Eighty thousand papers of one field
it cannot: they do not fit in a context window, re-reading the corpus for every question costs
more each time it is asked, and every pass returns a slightly different answer.

So the corpus is read once and what is left behind is markup. Statements are lifted out of the
text, typed against an ontology and stored with the fragment they came from. Downstream systems
query that instead of the texts, which makes the expensive pass a fixed cost rather than a
recurring one.

Which types exist is not the library's business. The core carries six concepts and no domain
vocabulary at all; the types, fields and predicates arrive at run time from packs of YAML, and the
steps that produce them are named in a configuration file rather than wired into the code. Reading
a different field, or reading papers differently, is a pack and a configuration, not a fork.

A node is worth querying only because it carries the fragment it came from. Every span stores the
exact substring together with the offsets it was taken at, so any statement in the markup can be
checked against the text that produced it, and a text layer that has drifted since ingest is
detectable instead of silently wrong.

```
L4  field map   portfolios of work, drift of topics
L3  topic       a cluster of related sources
L2  source      one document, read once
L1  node        a typed thing, of whichever types the loaded pack declares
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
- **Schema** — the ontology plugged in underneath: types, fields and predicates, each with an IRI
  and optional mappings to public vocabularies.

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
corpus/pack.yaml
corpus/pipeline.yaml
corpus/questions.yaml
corpus/README.md

$ atlas run corpus/pipeline.yaml paper.pdf
inputs 1	sources 1	renderings 1	statements 41	malformed 0	tokens 51204	cached_replies 0	nodes 33	unplaced 4	needs_review 6	violations 2	assertions 33	store corpus/store	94.318s

$ head -n 1 corpus/store/assertions.jsonl
{"id":"8c5c97324ba55420","agent":{"id":"run:2026-09-13T10:15:00+00:00","kind":"run","label":""},"at":"2026-09-13T10:15:00+00:00","target":{"id":"b3a1c4696f1af143","spans":[{"source_id":"3a750328a5e6","segment":1,"start":0,"end":54,"text":"Our model improves F1 by 3.4 points over the baseline."}],"schema_version":"2775c3049803","type":"Result","fields":{"statement":"Our model improves F1 by 3.4 points over the baseline."}},"supersedes":null,"confidence":null}
```

`init` writes a pack to fill in, a configuration naming it, a questions file and a note; edit the
pack and the run is about your domain. `run` prints one line: every count the steps it was
configured with left behind — how many statements the model offered, what they were charged, how
many were refused because their quote could not be located, how many landed through a relaxed
search and are worth a look, how many the pack rejected, and how many assertions were written —
then where the pass was written and what the store recorded it took. The configuration names the
store, and `--store dir` overrides it for one run. The store is append-only, so a second run lands
under what is already recorded rather than replacing it.

`scaffold(directory, templates)` is the same command as a function, and `templates` is a mapping
from a relative name to the text to write there: an application whose corpora have a shape of their
own hands in that shape instead of writing its own `init`.

To read a corpus under the six machine-learning types this project started with, name the pack
that still holds them. A pack is looked for beside the configuration that named it, then under the
working directory, then among the packs the wheel ships, so a bare name is enough for that last one:

```yaml
schema: ml_paper        # or a path: packs/ml_paper.yaml, ../shared/pack.yaml
```

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

schema = load(Path("pack.yaml"))
source = read_pdf(Path("paper.pdf"))
store = open_store({"jsonl": {"dir": "store"}})   # or "memory"; a store of your own registers too
store.add_source(source)

match = locate(source, quote, segment)           # a quote becomes a verified span, or None
node = Node(
    id="n1",
    type="Observation",                          # a type your pack declares, not one of ours
    fields={"summary": quote[:40]},
    spans=(match.span,),
    schema_version=schema.version,
)
assert schema.validate_node(node) == []          # violations, empty when the node fits the pack

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
configuration file other than the four it reserves: `schema`, `store`, `imports` and `steps`.

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
  model/             the metamodel: source, span, node, link, assertion, schema
  ontology/          reading packs off disk and merging them into one schema
  text.py            folding, normalising and tokenising, shared by relocation and indexing
  store/             the append-only log, in memory and on disk, and the projections over it
  steps/             ingest, rendering, extraction, relocation, validation, recording,
                     indexing, retrieval, answering
  pipeline.py        a configuration of step names run in order over one dict of state
  scaffold.py        the project skeleton `atlas init` writes
  llm.py             the chat client, with a disk cache in front of it
  cli.py             the two subcommands, run and init
packs/
  ml_paper.yaml      one domain's ontology: six node types and eight predicates
  README.md          what a pack is and how to write one
                     (shipped in the wheel; `atlas.ontology.builtin("ml_paper")` is its path)
pipeline.yaml        the default run over that pack
tests/               the suite; no network, no API key, no committed binaries
docs/
  architecture.md    the metamodel, the step model, the store, the open questions
  ontology.md        what a pack declares, how identity works, how the version is hashed
  evaluation.md      the measurement contract: competency questions, seams, negative controls
  initiative.ru.md   the Russian write-up of the initiative
CLAUDE.md            how to work in this repository: invariants, layout, direction
index.html           the project page
```

## Design

- Nothing under `atlas/` names a type, a field or a predicate of any domain. `tests/test_substrate.py`
  runs the shipped steps over an invented ontology and holds that claim to it.
- A step is a function from the run's state to the keys it adds, registered under a name. Replacing
  one is naming a different one in the configuration file.
- A type that crosses a step boundary lives with the step that defines it, and importing it from
  another step is normal. `atlas/model/` holds only what a store persists and every run exchanges.
- Writing is asserting: a store is an append-only log, and the graph is the projection of it. A
  correction supersedes; nothing is overwritten.
- The model is asked for a verbatim quote and never for character offsets, which it would invent;
  offsets are recovered by searching the segment text.

## Status

Working today: the metamodel and its projections; pack loading, merging, identity and validation;
an append-only store in memory and as JSON lines on disk, opened by the name a configuration gives
it, keeping the runs that wrote it and the schemas its objects name; the steps for PDF and plain-text
ingest, a markdown rendering that reads back into the same source and the same offsets, extraction
of typed statements one segment at a time, relocation of each quote into a span, validation against
the loaded pack, recording as assertions, and — over a store a build filled earlier — indexing,
term-overlap retrieval and an answer whose uncited lines are dropped; the cached model client; the
`run` and `init` subcommands.

Not implemented yet: link extraction, so a `Link` validates and stores but no step produces one;
canonicalisation across sources; the evaluation harness, whose contract is written in
`docs/evaluation.md` and whose code does not exist; the levels above L1; a store in a database. The
shipped ranking is term overlap with a length normalisation and nothing else — enough to answer
from hundreds of documents, and honest about missing a question phrased in words the text avoids.
One pack ships, for machine-learning papers, and it is an example rather than a core.

## Licence

Code is MIT, in `LICENSE`. Texts and diagrams are CC BY 4.0.
