# Architecture

Read this before changing code: what the substrate is, what the metamodel guarantees, how a run is
assembled, and what is open.

## Three layers, and the line between them

The **metamodel** in `atlas/model/` is six types and no domain content: `Source`, `Span`, `Node`,
`Link`, `Assertion`, `Schema`. It reads no files, loads no configuration and names no type of any
field. Everything else depends on it, and it depends on nothing.

The **ontology** is data. `atlas/ontology/load(*specs, base=None)` reads packs of YAML and merges
them into one `Schema`, versioned by the hash of the bytes it read. Which packs are loaded is a
line in a configuration file, so the vocabulary of a corpus is chosen at run time by the person
reading it. Each spec is resolved beside the configuration that named it, then under the working
directory, then among the packs the wheel ships -- `docs/ontology.md` says where and why.

The **pipeline** is a list of named steps. A step is a function `step(state, options) -> State`,
where `State` is `dict[str, Any]` and `options` is the model the step declared, absent when it
declared none: it receives everything the steps before it produced and returns the keys it adds.
`atlas/steps/__init__.py` is a dict from name to `Step` -- the function, the name it was registered
under, the state keys it declares and the options it takes -- `atlas/pipeline.py` resolves the
names in a configuration against it and calls them in order, and that is the entire mechanism.
Adding a step is writing a function and registering it; replacing one is editing a line of YAML;
neither is a reason to touch the pipeline or to fork the library.

What a step reads, what it adds and what it takes are declared where it is registered:

```python
class RetrieveOptions(Frozen):
    limit: int = LIMIT


@register("retrieve", requires=("store", "index", "question"), produces=("hits",),
          options=RetrieveOptions)
def retrieve(state: State, options: RetrieveOptions) -> State:
```

`from_config` checks the chain as it reads the file: a step that reads a key a later step produces
is refused by name, with the file in the message, instead of raising a `KeyError` from inside a
step. A key no step in the file produces is the caller's to supply -- a client, a question -- and
passes. That is the whole check on state keys: names, in order, no types and no solver.

The options are checked in the same pass and by the same rule -- refuse it while the file is open,
name what is wrong. The model is the declaration and the parser at once, `Frozen` forbids what it
does not name, and so a configuration reading `{retrieve: {limit: 8, treshold: 0.2}}` is refused
with `step 'retrieve': unknown option 'treshold'. It takes limit: int = 8` and the path of the file
in front of it, where before the misspelt key was swallowed and the step ran on its default. A
wrongly typed value is the same class of mistake and gets the same treatment. A step that takes
nothing declares `options=Nothing` -- which is also the default, so a step registered without an
`options=` at all takes none and refuses every one written under its name -- and a default lives in
the model and nowhere else, so the file and the signature cannot disagree. There is no path left
that accepts an option nothing reads.

### Why state keys are names and not types

`requires` and `produces` could carry a type per key and be compared pairwise when the file is read
-- `relocate` produces `nodes` as `tuple[Node, ...]`, `validate` reads them as the same -- and it
was measured against what it would catch before it was left out.

Against: of the eighteen keys the shipped steps exchange, seven are an `int` or a `str` whose name
already says everything a type would (`tokens`, `malformed`, `cached_replies`, `uncited`,
`assertions`, `at`, `question`); three carry an injected object (`store`, `client`, `schema`) and
two of those are Protocols supplied by the caller rather than by a step, which a pairwise
producer-to-consumer check never sees at all. What is left -- `sources`, `statements`, `nodes`,
`index`, `hits`, `answer` -- is exchanged between steps that already share the import: `retrieve`
imports `Index` from `index_nodes`, `answer` imports `Hit` from `retrieve`. The declaration would
restate the import, and it is the import, not the restatement, that fails when the type changes.

Against, harder: comparing `tuple[Hit, ...]` offered against `Iterable[Hit]` wanted is a subtype
question, and answering it at run time is a solver. Demanding that both ends write the same
annotation instead is a check on spelling. And a declaration is only as good as its author: nothing
compares a declared type to what the function actually returns, so a wrong one is caught by nothing
-- which is not hypothetical here, since `assert` declares `store` in `requires` and also produces
it, meaning "use the one the run carries, or open one", a presence claim the declaration cannot
express and enforcing it would break. Types on top of that would be built on sand.

For: it would catch two steps agreeing on a name and disagreeing on the thing. That is real, and it
is caught by the first run and by the test of either step, both of which are cheaper than a
mechanism twelve modules have to be rewritten for. So: no types on state keys. The options half of
the same problem pays -- an option is written by hand in a YAML file, by someone who cannot see the
signature, and nothing else checks it -- and that half is implemented.

Three things follow. A contributor can run any step on a laptop with no database and no services,
because the state between two steps is a dict of models that serialise to files you can read,
diff and hand-edit. A step can be replaced without touching its neighbours: relocation is a
function from a source and a quote to a `Match`, so swapping its search strategy changes nothing
on either side as long as the span still re-slices to its own text, and a different PDF parser is
a different `ingest_pdf`, not a change to extraction. Evaluation attaches at any seam, because a
run's state is a value and a step is scored by replaying recorded inputs, with no hook inside it.

Storage and IO live at the edge. The CLI in `atlas/cli.py` parses arguments, reads the
configuration, builds a client, runs the chain and prints the counts the state carries, where the
pass was written and what the store recorded it took; it names no step and no key. The
configuration is read first because reading it needs no key: a step's misspelt option is then what
a run reports, rather than an unset variable on a machine where nobody has exported one yet.
Which store a run writes into is the configuration's business, and `--store dir` overrides it with
a directory of JSON lines for the one run. The model client in `atlas/llm.py` is an edge resource too, passed into a step
rather than reached for inside one. `Client.complete` returns a `Reply` -- the text, the usage the
provider counted, and whether the disk cache answered -- so a caller can report what a run cost;
`ATLAS_CACHED_ONLY` makes a client replay that cache with no key and no network. `complete_json`
hands back the reply beside the object it parsed, so a step that asks for JSON can still report
what it spent: `extract_llm` adds `tokens`, what the calls it actually made were charged, and
`cached_replies`, how many came off the cache and cost nothing this time.

A **configuration** reserves four keys. `schema` names the packs to load, `store` is opened through
`atlas.store.open_store`, `imports` is a list of modules imported before the step names are
resolved -- which is how a configuration names a step that lives outside this tree -- and `steps` is
the list itself. Every other key belongs to whoever wrote the file and is kept, unread, in
`Pipeline.meta`: a name and a note for an interface are a supported thing to write down, not
behaviour that happens to work.

A run can be watched and entered part-way, because an interface that shows work as it happens must
not have to re-implement the loop. `Pipeline.initial(inputs, **context)` is the state a batch run
starts from and is public; `Pipeline.run(inputs, on_step=None, **context)` runs the chain over it
and calls `on_step(name, index, produced, state)` after each step, with the name the step was
configured under; `Pipeline.run_state(state, on_step=None)` runs the same chain over a state the
caller built, which is the shape of a request -- a question and a store, no inputs and no timestamp
to invent. After a batch run, and only when the state carries a store, the pipeline writes one
`Run`: the configuration's file name, `at`, the schema version, the counts the state held and the
wall time. Its id follows from its content, so a replayed pass is recorded under the id it carried
before; nothing is deduplicated, and two identical passes are two rows under one id. `summary(state)` and `counts(state)` report every value
in a state that is an integer or knows its own length; text is skipped. No shipped step returns a
redundant integer beside a value it already produced: `Index` answers `len()`, `hits` is a tuple,
and `uncited` survives only because lines the model wrote and the citation check dropped are not
recoverable from anything else in the state.

## The steps that ship

| Name | Reads from the state | Adds | Module |
|---|---|---|---|
| `ingest_pdf` | `inputs` | `sources` | `atlas/steps/ingest_pdf.py` |
| `ingest_text` | `inputs` | `sources` | `atlas/steps/ingest_text.py` |
| `ingest_markdown` | `inputs` | `sources` | `atlas/steps/markdown.py` |
| `render_markdown` | `sources` | `renderings` | `atlas/steps/markdown.py` |
| `extract_llm` | `sources`, `schema`, `client` | `statements`, `malformed`, `tokens`, `cached_replies` | `atlas/steps/extract_llm.py` |
| `relocate` | `sources`, `statements`, `schema` | `nodes`, `unplaced`, `needs_review` | `atlas/steps/relocate.py` |
| `validate` | `nodes`, `schema` | `nodes`, `violations` | `atlas/steps/validate.py` |
| `assert` | `sources`, `nodes`, `schema`, `at`, `store` | `store`, `assertions`, `agent` | `atlas/steps/record.py` |
| `index_nodes` | `store` | `index` | `atlas/steps/index_nodes.py` |
| `retrieve` | `store`, `index`, `question` | `hits` | `atlas/steps/retrieve.py` |
| `answer` | `hits`, `question`, `client`, `schema` | `answer`, `uncited` | `atlas/steps/answer.py` |

What each may be given under its name in a configuration, copied from the message the library
itself prints when an option is wrong -- anything not on this line is refused as the file is read:

| Name | Options |
|---|---|
| `ingest_pdf` | no options |
| `ingest_text` | `split: Literal['blank-line', 'whole', 'window'] = 'blank-line', window: int = 2000` |
| `ingest_markdown` | no options |
| `render_markdown` | `out: str` (required) |
| `extract_llm` | `segment: str = 'segment'` |
| `relocate` | no options |
| `validate` | no options |
| `assert` | `agent: Literal['human', 'model', 'run'] = 'run', label: str = ''` |
| `index_nodes` | `name: str = 'index.json', rebuild: bool = False` |
| `retrieve` | `limit: int = 8` |
| `answer` | `system: str \| None = None` |

The first eight are a build: documents in, assertions out. The last three are a question, and run
over a store that a build filled earlier -- `Pipeline.run_state` with `question` and `client` in the
state, no inputs and no timestamp to invent. `question` and `client` are produced by no step, which
is exactly why the order check lets them through: they are the caller's to supply.

`Pipeline.initial` seeds the state with `inputs`, the loaded `schema` and `at`, the one timestamp
every assertion of the run then carries, the store the configuration named if it named one, plus
whatever the caller passes as context — the client, a store of its own, a question. Unwritten:
link extraction, canonicalisation of nodes across sources, evaluation. Each is a step with a name
that no configuration can yet use.

### Where a type that crosses a step boundary lives

With the step that defines it, and importing it from another step is normal. `Statement` is in
`atlas/steps/relocate.py`, `Index` in `index_nodes.py`, `Hit` in `retrieve.py`, `Answer` in
`answer.py`, and `extract_llm` imports `Statement` rather than the metamodel growing a place for it.

`atlas/model/` holds only what the substrate is made of: the things a store persists and every run
exchanges whichever steps are configured. The test is mechanical -- is it asserted, does it carry a
`schema_version`, does it outlive the state dict? `Run` answers yes to the first and is therefore in
`atlas/model/` despite not being one of the six; `Hit` answers no to all three. The alternative rule
would pull every future step's intermediate into the metamodel, which is what "six concepts and no
domain content" exists to prevent.

## Asking a marked-up corpus a question

Three steps, each the mechanical part of a job every consumer was otherwise writing itself.

`index_nodes` counts the terms of `Node.text()` with `atlas.text.tokenise` -- the same folding that
placed the spans, so a node located perfectly well cannot be missed by a search that folded
differently -- and writes the postings to `store.artifact("index.json")`. A store with nowhere to
put a file answers `None` and the index is built per process instead. The file carries a signature
over the node ids it was built from, so a corpus that gained or re-extracted a node gets a new index
and one that did not gets the file already on disk; a truncated file is a miss, not a failed run.
`rebuild` forces the build for the one thing a signature cannot see, a file edited under a corpus
that did not change, and `name` says what to call the file -- a file name and not a path, because
which directory a derived file may go in is the store's answer and a configuration may not overrule
it by writing `../index.json`.

`retrieve` ranks with `overlap`: distinct question terms the node contains, over the square root of
its length. No idf, no phrases, no vectors, no lemmatisation, and the docstring says so -- a question
phrased in words the text does not use finds nothing. The ranking a demo wants is not the ranking
every consumer wants, and the seam for another one is the seam the library already has: write a step
and name it in the configuration instead of this one. `overlap` and `Index` are public, so such a
step keeps whichever half it likes. There is no registry of scorings inside the step: that would be
the step registry again, one level down and configurable from two places. The ranked ids are
resolved back through `store.get_nodes`, because the index outlives the node it indexed and a
superseded node must not be quoted as evidence.

`answer` is the invariant's counterpart in prose: no citation, no statement. The model is shown each
hit under its `node.ref` and asked for one statement per line ending in the references it rests on;
`keep_cited(text, known)` drops every line citing nothing known and returns what was cited, and
`uncited` counts the loss. The unit is the line, which is why the prompt forbids headings and
tables -- a consumer wanting either needs its own unit and its own prompt, and `keep_cited` is
public so it can keep the rule while changing the prose. The prompt is deliberately not an option:
`keep_cited` enforces what that prompt asks for, so a configuration able to replace the text would
be able to stop asking for the citations every line is then dropped for, and the run would come back
empty with nothing in the file to say why. `system` is the option, and it changes the voice in front
of the prompt rather than the contract inside it.

## What the metamodel guarantees

`Source` is something that was read, after its text layer has been fixed. `Segment` is one numbered
part of it — a page, a paragraph, a window; the metamodel does not care which — and its text is the
coordinate system spans are measured against. `Source.id` names what was read; `text_hash` names
the text that came out of it, and the two differ exactly when a reader change moved the offsets
under stored spans.

`Span` is a verbatim region located by character offsets into one segment. Its validator enforces
`end - start == len(text)`, and the text is stored beside the offsets so a span can be checked
without loading the source. `Span.of` cuts the text out of the segment instead of being handed it,
which is why a span cannot lie about where it came from.

`Node` is a typed thing and `Link` a typed relation between two node ids. Both are `Evidenced`:
at least one span, and all spans from a single source, because a thing evidenced in two documents
is two things until something asserts they are one. Both carry `schema_version`, and neither
validates its own type — that is the loaded `Schema`'s business, reported and not raised.

A node also answers two questions a reader asks. `node.ref` is what a person is shown and an
answer cites: the source it was read from and a stub of its own content hash, derived from the node
alone, so the same claim on the same quote carries the same reference after the next extraction --
unlike an ordinal minted over whatever the store currently projects, which renumbers every run.
`node.text()` is its field values and its quotes as one string, which is what indexing, ranking and
prompting all want and each used to write out for itself. What to call it is the schema's business:
`Schema.label_of(node)` returns the field its type declared as `label_field`, else its first
declared field, else the type name.

`Assertion` is one act of asserting: an agent, a time, the target carried whole, and optionally the
assertion it supersedes. Carrying the target whole rather than referencing it makes the log
self-contained: replaying it reconstructs every state the graph has been in. An `Agent` is one of
three kinds -- `AgentKind`, exported by `atlas.model` -- and that name is what the `assert` step
offers a configuration, so the kinds a file may write are the kinds the metamodel has and a fourth
spelling is refused as the file is read rather than inside the step.

`Run` is in `atlas/model/` but is not one of the six: it is a record *about* a pass rather than a
claim about the world, kept because what a pass cost and how much of it survived is otherwise lost
when the process ends. It is written to a store and read back; nothing runs it.

`Schema`, `TypeDef`, `PredicateDef` and `FieldDef` are the loaded ontology. Lookup is by local name
or by identity, with CURIEs expanded through the prefix map, so `find_type("Measure")`,
`find_type("ex:Measure")` and the full IRI are one type. See `docs/ontology.md`.

## The store is a history, not a table

`atlas/store/` holds sources and an append-only body of assertions. `nodes()` and `links()` are the
projection `current` makes over that body: the latest assertion per target id that nothing
supersedes. Nothing is ever updated or deleted, so a re-extraction adds assertions under the
judgements already recorded instead of overwriting them, and `assertions(target_id)` returns the
history behind any one of them.

Two implementations, deliberately: `MemoryStore` is dicts and a list, `JsonlStore` a directory of
JSON-line logs. `assert_` refuses an assertion whose evidence stands on a source the store has
never held: only a store can say whether something was read, and without the check a store
accumulates provenance nobody can re-verify.

### What a read costs

A store is read from a request handler as well as from a batch job, so every method of the
protocol states its cost, in `n` sources held, `m` assertions written and `k` nodes the history
currently projects to: `get_source`, `get_node` and `get_schema` are O(1), `get_nodes` is O(ids),
`sources` is O(n), `nodes`, `links` and `by_type` are O(k), `assertions` is O(m). An implementation
that cannot meet one says so on its own method.

Both shipped stores meet them by keeping the projection beside the log and rebuilding it on the
first read after a write: `MemoryStore` drops it when `assert_` appends, `JsonlStore` keys it on
the size and modification time of the file, so its own append and a write by another process both
invalidate it, at the cost of one `stat` per read. The cache is derived from the log and never
consulted for what the log does not say, which is what keeps it from disagreeing with the history.
Measured on 2 000 assertions: a full reparse and reprojection is 163 ms, a cached `nodes()` 0.08 ms
and a cached `get_node()` 0.014 ms.

### What a store keeps besides the history

`add_run` / `runs` hold `Run` records: what one pass cost and how much of what it claimed survived
-- id, time, configuration, schema version, agent, `counts`, seconds, notes. The counts are
whatever the configuration counted; the store names none of them. Nothing supersedes a run.

`add_schema` / `get_schema` keep the schemas objects name, addressed by `Schema.version`, so a
reader resolves a stored `schema_version` back to the vocabulary it was written under instead of
loading a pack and assuming it is the right one. Writing a version twice is a no-op. The `assert`
step writes the schema of its run alongside the assertions, so a store that holds an object also
holds the vocabulary that object names.

`location` is where the store lives, or `None`; `artifact(name)` is a path a derived file such as a
search index may use, or `None` from a store with nowhere to put one. A step asks rather than
reaching into an implementation it was handed.

### Opening the store a configuration names

Stores are registered by name the way steps are -- `@register_store("jsonl")` over a factory --
and `open_store(spec, base)` resolves a specification: `"memory"` for the defaults, or
`{"jsonl": {"dir": "store"}}` for a name with its options, whose paths are resolved against `base`
so a configuration and the store it names travel together. A store outside this tree registers
itself the way an out-of-tree step does, and needs no change here.

## One ruling on what a dash is

`atlas/text.py` is the only place that folds text. `fold` returns a folded copy together with the
source offset of every character it kept, which is what lets relocation search a relaxed text and
still return offsets into the original; `normalise` and `tokenise` are the same table without the
offsets, for an index or a question. They are one module because they were two: a quote located
through one normalisation and indexed through another misses a search that should have hit, and no
test on either side can see it. Nothing here touches a stored text layer -- all three take a copy.

## Provenance end to end

No provenance, no node. The rule is enforced by the types rather than by a prompt: `spans` has
`min_length=1` and a `Span` cannot be built without the exact substring it points at. The model is
asked for a quote and never for offsets: offsets it produces are invented, and a wrong offset is
worse than a missing one because it still looks like provenance. `extract_llm` sends one segment
and receives typed statements each carrying a quote; `relocate` recovers the offsets by searching
the source.

`locate` tries three searches in order, each over every segment with the segment being read tried
first: an exact `str.find`; the same search on a folded copy with dashes and quotation marks
unified and whitespace runs collapsed, which covers a model that retyped a line break as a space;
then a `rapidfuzz` partial alignment scored against `THRESHOLD`. Each relaxation records itself in
`Match.method` and lowers `Match.confidence`, and the fuzzy path sets `needs_review` because its
boundaries were chosen by edit distance rather than by the quote. A fuzzy span is grown outward to
the nearest whitespace, since alignment stops mid word and half a word cannot be re-verified by a
reader. The folded copy keeps a map back to original offsets, so every path returns a span that
re-slices to exactly its own text; `_span_at` is the one place a `Span` is constructed.

When relocation fails, `locate` returns `None`, the statement is discarded and `unplaced` counts
it; nothing is placed somewhere plausible. `malformed` counts reply items that did not parse and
`violations` carries what the pack refused, so the gap between what the model offered and what was
written down stays visible in the run's own summary. A quote that relocates onto a node id already
minted is skipped and not counted: nothing was refused.

The text layer is frozen at ingest for the same reason. Every span ever stored indexes
`Source.segment_text(segment)` as ingest produced it, so normalising, dewrapping or de-hyphenating
there would move offsets that stored objects already point at. Cleanups belong in the search, on a
folded copy, never in the stored text. The markdown rendering stores segment text unaltered, which
is why `read_markdown` refuses a file whose declared segment count disagrees with its markers
instead of escaping a segment that happens to contain a marker line.

## Schema versioning

`load` hashes the raw bytes of the packs it read, in the order given, and uses the first twelve hex
characters as `Schema.version`. The hash is over bytes, so a comment or a reordering changes the
version too. That is deliberate: the version answers which files produced this node, not whether
two schemas mean the same thing.

Every node and link carries that version. Without it, an object written under a type that has since
been renamed is uninterpretable, and the meaning of a corpus depends on a file that no longer
exists. When a pack changes under an existing corpus, old objects stay valid artifacts and keep
their old version string; nothing rewrites them. Re-validating them reports what no longer fits,
and re-extracting produces objects with the new version and, because a node id hashes the located
coordinates and not the schema, the same ids wherever text, type and fields did not change.

## Determinism and cost

A node id is a hash over source id, the located coordinates, the type name and the fields, so the
same segment extracted twice yields the same ids and two runs are compared by id, not by position.
A link id hashes what it relates and what it stands on, and not its fields, so annotating a link
later does not fork it. An assertion id hashes agent, time and target, so replaying an unchanged
pass at the same `at` writes the assertion it wrote before rather than a second copy of it.

`atlas/llm.py` puts a disk cache in front of the model, keyed by a hash of base URL, model,
temperature, system prompt, prompt and schema; temperature defaults to `0.0`. The cache is part of
the contract rather than an optimisation. A second run over an unchanged corpus makes no requests,
and `ModelConfig.cached_only` -- `ATLAS_CACHED_ONLY=1`, under which `from_env` stops requiring a
key -- turns a miss into a `CacheMiss` instead of a call, which is how a downstream change is
tested without paying for extraction again. Iterating on relocation or on
validation is therefore free; only a changed prompt misses the cache, which it should.

## Open questions

- No step produces a `Link`, so the markup is a set of nodes and not yet a graph.
- Canonicalisation is unwritten: two nodes stating the same thing in different words stay two.
- `assert` never sets `supersedes`; superseding needs a read that finds the live assertion for a
  target, and nothing offers one yet.
- The search unit is one segment, so a quote straddling a segment break cannot be located as one span.
- `Node.fields` is `dict[str, str]`, so a pack constrains field names and nothing else; `FieldDef.datatype`
  is declared and unchecked.
- `load` does not check a predicate's domain and range against known type names; a typo surfaces
  later as a link violation.
- `by_type` on a store compares terms exactly: it neither expands a CURIE nor descends a hierarchy,
  since a store holds no schema.
- Retrieval is term overlap over one index in one JSON file. There is no idf, no embedding and no
  graph search; a question in an inflected form the text does not use finds nothing.
- `keep_cited` works a line at a time, so a model answering in one uncited paragraph answers nothing
  and a table loses every row without its own citation.
- A run needs the three model variables even when no step calls a model: the CLI builds one client
  for every run. The configuration is read first, so a file that is wrong is refused without them,
  but a valid chain that calls no model still asks for all three.
- `Match.needs_review` is counted and printed; no step consumes it and there is no review path.
- `cached_only` has no CLI flag; a key-free replay is `ATLAS_CACHED_ONLY=1` in the environment.
- Multi-span nodes are representable and never produced: one statement, one span.
