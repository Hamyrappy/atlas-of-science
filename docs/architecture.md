# Architecture

Read this before changing code: the pipeline's shape, what the artifacts guarantee, what is open.

## The stage model

A stage is a pure function from artifacts to artifacts. It takes values defined in
`atlas/contracts.py`, returns values defined there, and does not know where either came from.
Storage lives at the edge: the CLI in `atlas/cli.py` reads a file, calls one library function and
writes the result, and a stage opens only the paths it was handed. The model client in
`atlas/llm.py` is an edge resource too, passed into a stage rather than reached for inside one.

Three things follow, and they are the reason for the shape. A contributor can run any stage on a
laptop with no database and no services, because the state between two stages is a file you can
read, diff and hand-edit; `atlas extract` writes one card per line for that reason. A stage can be
replaced without touching its neighbours: relocation is a function from a document and a quote to a
`Match`, so swapping its search strategy changes nothing on either side as long as the span still
re-slices to its own text, and a different PDF parser is a different `Document`, not a change to
extraction. Evaluation attaches at any seam, because `EvalReport` names its stage as a string and a
stage is scored by replaying recorded inputs, with no hook inside it. Artifacts are frozen models
with tuple fields: build them with constructor calls, because nothing in the pipeline mutates one
in place.

## Stages

| Stage | Input | Output | Module |
|---|---|---|---|
| ingest | PDF path | `Document` | `atlas/ingest/pdf.py` |
| render | `Document` | markdown file | `atlas/ingest/pdf.py` |
| restore | markdown file | `Document` | `atlas/ingest/markdown.py` |
| ontology load | core YAML plus optional extension | `Ontology` | `atlas/ontology/__init__.py` |
| validate | `Card` or `Edge`, `Ontology` | list of violations | `atlas/ontology/__init__.py` |
| relocate | `Document`, quote | `Match` | `atlas/extract/relocate.py` |
| extract | `Document`, `Ontology`, client | `ExtractionResult` | `atlas/extract/cards.py` |
| canonicalisation | cards | cards | absent |
| edge extraction | cards, `Document` | `Edge` | absent |
| retrieval | `QuestionSet`, cards | `RetrievalResult` | absent |
| answering | `RetrievalResult`, cards | `Answer` | absent |
| evaluation | any stage's output | `EvalReport` | absent |

The bottom five rows have no implementation. `Edge`, `QuestionSet`, `RetrievalResult`, `Answer` and
`EvalReport` are declared in `atlas/contracts.py` and used by no stage today; they are written down
because adding a field later is cheap and renaming one is not. Canonicalisation maps cards to cards
and needs no type of its own.

## Artifacts

Field lists live in `atlas/contracts.py`. Below is what each type is for and what it guarantees.

`Page` is one page of text in the coordinate system spans are measured against; numbers are 1-based
and come from the parser. `Document` is a source after ingest, and its page text is final: ingest
with a different parser produces a different document id rather than a mutated document.

`Span` is a verbatim fragment located by character offsets into one page. Its validator enforces
`end - start == len(text)`, and the text is stored beside the offsets so a span can be checked
without loading the document, making a drifted text layer detectable instead of silently wrong.

`Card` is one typed statement from one document. It cannot be constructed with zero spans and it
names the ontology version it was written under. Its type and field keys are checked by the
ontology, not by the class.

`Edge` is a typed relation between two card ids, carrying its own supporting span; no stage
produces one yet. `TypeDef` is a node type with an optional parent and the fields it declares, and
`PredicateDef` a relation type with the types it may connect. `Ontology` is a loaded core plus an
optional extension, versioned by the content hash of the source bytes; every extension type
descends from a core type, which keeps two domains comparable.

`QuestionKind` is what a competency question asks for, and retrieval is meant to be scored per
kind. `CompetencyQuestion` is a question the markup should answer, with its acceptance criteria;
its `split` keeps the bank honest, since `dev` questions may steer the ontology and `test`
questions are only ever reported on. `QuestionSet` is a versioned bank of them for one domain.

`Retrieved` is one card id with the score that ranked it, and `RetrievalResult` the ranked list
for one question. `Answer` is the answer text for one question with the card ids it was allowed to
use. `EvalReport` is the metrics for one stage of one run plus the samples behind them, because a
number whose cases cannot be inspected cannot be argued with.

## Provenance end to end

No provenance, no node. The rule is enforced by the contracts rather than by a prompt:
`Card.spans` has `min_length=1` and a `Span` cannot be built without the exact substring it
points at. The model is asked for a quote and never for offsets: offsets it produces are
invented, and a wrong offset is worse than a missing one because it still looks like provenance.
`atlas/extract/cards.py` sends the page text and receives typed statements each carrying a quote,
and `atlas/extract/relocate.py` recovers the offsets by searching the page.

`locate` tries three searches in order, each over every page with the page being read tried
first: an exact `str.find` on the page text; the same search on a folded copy with dashes and
quotation marks unified and whitespace runs collapsed, which covers a model that retyped a line
break as a space; then a `rapidfuzz` partial alignment scored against `THRESHOLD`. Each relaxation
records itself in `Match.method` and lowers `Match.confidence`, and the fuzzy path sets
`needs_review` because its boundaries were chosen by edit distance rather than by the quote. A
fuzzy span is grown outward to the nearest whitespace, since alignment stops mid word and half a
word cannot be re-verified by a reader. The folded copy keeps a map back to original offsets, so
every path returns a span that re-slices to exactly its own text; `_span_at` is the one place a
`Span` is constructed and asserts that.

When relocation fails, `locate` returns `None`, the statement is discarded, and
`ExtractionResult.dropped` counts it; nothing is placed somewhere plausible. The same counter
covers reply items that do not parse and cards the ontology rejects, so the gap between what the
model offered and what was written down stays visible. A quote that relocates onto a card id
already written is skipped and not counted as dropped: nothing was refused.

The text layer is frozen at ingest for the same reason. Every span ever stored indexes
`Document.page_text(page)` as ingest produced it, so normalising, dewrapping or de-hyphenating
there would move offsets that artifacts on disk already point at. Cleanups belong in the search,
on a folded copy, never in the stored text. The markdown rendering stores page text unaltered for
the same reason, so `read_markdown` refuses a file whose declared page count disagrees with its
markers instead of escaping a page that happens to contain a marker line.

## Ontology versioning

`load` reads the core file and the optional extension, hashes the raw bytes of both, and uses
the first twelve hex characters as `Ontology.version`. The hash is over bytes, so a comment or a
reordering changes the version too. That is deliberate: the version answers which file produced
this card, not whether two schemas mean the same thing.

Every card carries that version. Without it, a card written under a type that has since been
renamed is uninterpretable, and the meaning of a corpus depends on a file that no longer exists.
When the ontology changes under an existing corpus, old cards stay valid artifacts and keep their
old version string; nothing rewrites them. Re-validating them with `validate_card` reports what no
longer fits, and re-extracting produces cards with the new version and, because a card id hashes
the quote and not the schema, the same ids wherever text and type did not change.

## Determinism and cost

A card id is a hash over document id, page, type name and quote, so the same page extracted twice
yields the same ids and two runs are compared by id, not by position. The page hashed is where the
quote was found, not the page being read.

`atlas/llm.py` puts a disk cache in front of the model, keyed by a hash of base URL, model,
temperature, system prompt, prompt and schema; temperature defaults to `0.0`. The cache is part of
the contract rather than an optimisation. A second run over an unchanged corpus makes no requests,
and setting `cached_only` on a `Client` turns a miss into an error instead of a call, which is how
a downstream change is tested without paying for extraction again. Iterating on relocation or on
validation is therefore free; only a changed prompt misses the cache, which it should.

## Open questions

- How the type schema is produced is open: a hand-written core now, an agent per domain later.
- Edge extraction is unwritten, so the markup is a set of cards and not yet a graph.
- Canonicalisation is unwritten: two cards stating the same thing in different words stay two.
- The search unit is one page, so a quote straddling a page break cannot be located as one span.
- `Card.fields` is `dict[str, str]`, so the ontology constrains field names and nothing else.
- `load` does not check a predicate's domain and range against known type names; a typo in an
  extension surfaces later as an edge violation.
- Retrieval over cards is unwritten, and with it the choice of lexical, embedding or graph search.
- Nothing defines run storage beyond one JSONL file per document, or how two runs are reconciled.
- `Match.needs_review` is counted and printed; no stage consumes it and there is no review path.
- `cached_only` has no CLI flag, so a key-free replay means building a `ModelConfig` in Python.
- Multi-span cards are representable and never produced: one statement, one span.
