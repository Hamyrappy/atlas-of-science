# Architecture

Read this before changing code: what the substrate is, what the metamodel guarantees, how a run is
assembled, and what is open.

## Three layers, and the line between them

The **metamodel** in `atlas/model/` is six types and no domain content: `Source`, `Span`, `Node`,
`Link`, `Assertion`, `Schema`. It reads no files, loads no configuration and names no type of any
field. Everything else depends on it, and it depends on nothing.

The **ontology** is data. `atlas/ontology/load(*paths)` reads packs of YAML and merges them into
one `Schema`, versioned by the hash of the bytes it read. Which packs are loaded is a line in a
configuration file, so the vocabulary of a corpus is chosen at run time by the person reading it.

The **pipeline** is a list of named steps. A step is a function `step(state, **options) -> State`,
where `State` is `dict[str, Any]`: it receives everything the steps before it produced and returns
the keys it adds. `atlas/steps/__init__.py` is a dict from name to function, `atlas/pipeline.py`
resolves the names in a configuration against it and calls them in order, and that is the entire
mechanism. Adding a step is writing a function and registering it; replacing one is editing a line
of YAML; neither is a reason to touch the pipeline or to fork the library.

Three things follow. A contributor can run any step on a laptop with no database and no services,
because the state between two steps is a dict of models that serialise to files you can read,
diff and hand-edit. A step can be replaced without touching its neighbours: relocation is a
function from a source and a quote to a `Match`, so swapping its search strategy changes nothing
on either side as long as the span still re-slices to its own text, and a different PDF parser is
a different `ingest_pdf`, not a change to extraction. Evaluation attaches at any seam, because a
run's state is a value and a step is scored by replaying recorded inputs, with no hook inside it.

Storage and IO live at the edge. The CLI in `atlas/cli.py` parses arguments, builds a client and a
store, calls `Pipeline.from_config(...).run(...)` and prints the counts the state carries; it names
no step and no key. The model client in `atlas/llm.py` is an edge resource too, passed into a step
rather than reached for inside one.

## The steps that ship

| Name | Reads from the state | Adds | Module |
|---|---|---|---|
| `ingest_pdf` | `inputs` | `sources` | `atlas/steps/ingest_pdf.py` |
| `render_markdown` | `sources` | `renderings` | `atlas/steps/markdown.py` |
| `ingest_markdown` | `inputs` | `sources` | `atlas/steps/markdown.py` |
| `extract_llm` | `sources`, `schema`, `client` | `statements`, `malformed` | `atlas/steps/extract_llm.py` |
| `relocate` | `sources`, `statements`, `schema` | `nodes`, `unplaced`, `needs_review` | `atlas/steps/relocate.py` |
| `validate` | `nodes`, `schema` | `nodes`, `violations` | `atlas/steps/validate.py` |
| `assert` | `sources`, `nodes`, `at`, `store` | `store`, `assertions` | `atlas/steps/record.py` |

`Pipeline.run` seeds the state with `inputs`, the loaded `schema` and `at`, the one timestamp every
assertion of the run then carries, plus whatever the caller passes as context — the client and the
store. Unwritten: link extraction, canonicalisation of nodes across sources, retrieval, answering,
evaluation. Each is a step with a name that no configuration can yet use.

`Statement` lives in `atlas/steps/relocate.py` because it is the contract between any extractor and
relocation, and not the property of the one extractor that ships: an extractor that reads tables,
or a human filling a form, produces the same thing.

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

`Assertion` is one act of asserting: an agent, a time, the target carried whole, and optionally the
assertion it supersedes. Carrying the target whole rather than referencing it makes the log
self-contained: replaying it reconstructs every state the graph has been in.

`Schema`, `TypeDef`, `PredicateDef` and `FieldDef` are the loaded ontology. Lookup is by local name
or by identity, with CURIEs expanded through the prefix map, so `find_type("Measure")`,
`find_type("ex:Measure")` and the full IRI are one type. See `docs/ontology.md`.

## The store is a history, not a table

`atlas/store/` holds sources and an append-only body of assertions. `nodes()` and `links()` are the
projection `current` makes over that body: the latest assertion per target id that nothing
supersedes. Nothing is ever updated or deleted, so a re-extraction adds assertions under the
judgements already recorded instead of overwriting them, and `assertions(target_id)` returns the
history behind any one of them.

Two implementations, deliberately: `MemoryStore` is a dict and a list, `JsonlStore` two files of
JSON lines that are reparsed and reprojected on every read. Neither keeps an index, because an
index is the first thing that can disagree with the log. `assert_` refuses an assertion whose
evidence stands on a source the store has never held: only a store can say whether something was
read, and without the check a store accumulates provenance nobody can re-verify.

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
and setting `cached_only` on a `Client` turns a miss into an error instead of a call, which is how
a downstream change is tested without paying for extraction again. Iterating on relocation or on
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
- Retrieval over nodes is unwritten, and with it the choice of lexical, embedding or graph search.
- A run needs the three model variables even when no step calls a model, because the CLI builds the
  client before it reads the configuration.
- `Match.needs_review` is counted and printed; no step consumes it and there is no review path.
- `cached_only` has no CLI flag, so a key-free replay means building a `Client` in Python.
- Multi-span nodes are representable and never produced: one statement, one span.
