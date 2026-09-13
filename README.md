# Atlas of Science

An open library for machine-readable scientific markup: a corpus is read once and turned into
typed cards, each bound to a verbatim fragment of its source.

Project page: [`index.html`](index.html) · Russian overview: [`docs/initiative.ru.md`](docs/initiative.ru.md)

## Why

A language model reads one paper without any markup at all. Eighty thousand papers of one field
it cannot: they do not fit in a context window, re-reading the corpus for every question costs
more each time it is asked, and every pass returns a slightly different answer.

So the corpus is read once and what is left behind is markup. Statements are lifted out of the
text, given types from a shared ontology and stored as cards. Downstream systems query the cards
instead of the texts, which makes the expensive pass a fixed cost rather than a recurring one.

A card is worth querying only because it carries the fragment it came from. Every span stores the
exact substring together with the offsets it was taken at, so any statement in the markup can be
checked against the page that produced it, and a text layer that has drifted since ingest is
detectable instead of silently wrong.

```
L4  field map   portfolios of work, drift of topics
L3  topic       a cluster of related documents
L2  document    one source, read once
L1  card        Result · Method · Claim · Dataset
L0  span        a verbatim fragment of the source
```

No provenance, no node.

## Install

```bash
pip install -e ".[dev]"
```

`atlas extract` talks to a chat-completions endpoint and reads three environment variables:
`ATLAS_BASE_URL` (the base URL of the endpoint), `ATLAS_MODEL` (the model name sent with each
request) and `ATLAS_API_KEY` (the bearer token). Replies are cached under `.atlas-cache/`, so a
repeated run over unchanged input makes no requests.

## Quickstart

```console
$ export ATLAS_BASE_URL=https://api.example.com/v1 ATLAS_MODEL=your-model ATLAS_API_KEY=secret

$ atlas ingest paper.pdf --out markdown/
4f3c2b1a9e8d	12	markdown/4f3c2b1a9e8d.md

$ atlas extract markdown/4f3c2b1a9e8d.md --out cards.jsonl
cards 37	dropped 4	needs review 6

$ head -n 3 cards.jsonl
{"id":"9f2c41ab7d0e5b83","type":"Result","fields":{"statement":"F1 rises by 3.4 points","value":"3.4"},"spans":[{"doc_id":"4f3c2b1a9e8d","page":6,"start":812,"end":866,"text":"Our model improves F1 by 3.4 points over the baseline."}],"run_id":"20260913T101500Z","ontology_version":"5d41402abc4b"}
{"id":"c07be4185a93d216","type":"Dataset","fields":{"name":"public benchmark"},"spans":[{"doc_id":"4f3c2b1a9e8d","page":6,"start":1187,"end":1240,"text":"We evaluate on the public benchmark released in 2019."}],"run_id":"20260913T101500Z","ontology_version":"5d41402abc4b"}
{"id":"3ad8f0b6e2c14975","type":"Claim","fields":{"statement":"attention carries the gain"},"spans":[{"doc_id":"4f3c2b1a9e8d","page":7,"start":2043,"end":2095,"text":"Ablating the attention layer costs 3.4 points of F1."}],"run_id":"20260913T101500Z","ontology_version":"5d41402abc4b"}
```

`ingest` prints one line per PDF: document id, page count, path written. `extract` takes either
that markdown rendering or the PDF itself, writes one card per line, and reports how many
statements it refused because their quote could not be found on the page, and how many landed
through a relaxed search and are worth a look.

## Layout

```
atlas/
  contracts.py       the artifact types every stage exchanges; frozen
  ontology/
    __init__.py      loading, merging, card and edge validation
    core.yaml        the shared core: six node types, eight predicates
  ingest/
    pdf.py           a PDF becomes a Document and a markdown rendering
    markdown.py      that rendering read back into the same Document
  extract/
    cards.py         one model call per page, typed statements out
    relocate.py      a quoted fragment placed back into the page text as a Span
  llm.py             the chat client, with a disk cache in front of it
  cli.py             the two subcommands, ingest and extract
tests/               77 tests; no network, no API key, no committed binaries
docs/
  architecture.md    the stage model, what each artifact guarantees, the open questions
  ontology.md        the core, how an extension descends from it, how the version is hashed
  evaluation.md      the measurement contract: competency questions, seams, negative controls
  initiative.ru.md   the Russian write-up of the initiative
index.html           the project page
```

## Design

- Every stage is a function from artifacts to artifacts, with no state shared between stages.
- The models in `atlas/contracts.py` are the only thing a stage may rely on in another stage.
- The ontology is a YAML file rather than code, and its content hash travels on every card.
- The model is asked for a verbatim quote and never for character offsets, which it would invent;
  offsets are recovered by searching the page text.
- There is no storage layer: stages read and write files, and a database can be introduced once a
  query needs one.

## Status

Working today: PDF ingest, with a markdown rendering that reads back into the same document and
the same page offsets; the ontology loader, with domain extensions, inherited fields, and card
and edge validation; card extraction over a document page by page, each card bound to a located
span and dropped when no span can be found; the cached model client; the `ingest` and `extract`
subcommands.

Not implemented yet: edge extraction, so `Edge` and `validate_edge` exist but nothing produces a
relation; retrieval, answering and evaluation, whose artifact types are declared in
`atlas/contracts.py` and unused; the levels above L1; any index or storage. Only the core
ontology ships with the library; no domain extension does.

## Licence

Code is MIT, in `LICENSE`. Texts and diagrams are CC BY 4.0.
