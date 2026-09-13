# Working in this repository

Atlas of Science is a library for machine-readable scientific markup: a corpus is read once, statements become typed cards, and every card is bound to a verbatim fragment of its source. This file is for coding agents and for the people directing them. It states what must not break, where things go, and how the work is divided.

## Read in this order

1. `README.md` — what the library does and how to run it.
2. `docs/architecture.md` — the stage model, the artifacts, provenance end to end.
3. `atlas/contracts.py` — the artifact types. Read the file itself; nothing here restates it.

Then the module you are about to change, and its tests. Do not start from a grep.

## The three invariants

Break any of these and the markup stops being worth more than the text it came from.

1. **No provenance, no node.** A card is created with at least one span. A span is created from a document through `Span.of`, which takes the text from the page rather than being told it, so offsets and quote cannot disagree. A statement whose quote cannot be located is dropped and counted, never stored.
2. **The text layer is frozen at ingest.** `Document.pages[i].text` is the sole coordinate system for every span that will ever point into that document. Never normalise, strip or reflow it after ingest. `Document.text_hash` names the text layer and is checked when a rendering is read back; an edited rendering is refused.
3. **A card names the ontology it was written under.** `ontology_version` is the content hash of the schema files. A card written last month must stay interpretable after today's schema edit.

The model is asked for a verbatim quote and never for character offsets, which it would invent. Recovering offsets is `atlas/extract/relocate.py` and nowhere else.

## Layout and what belongs where

```
atlas/contracts.py     artifact types; the only thing one package may rely on in another
atlas/ontology/        loading, merging and validating the schema; the schema is data, not code
atlas/ingest/          a source becomes a Document and a markdown rendering
atlas/extract/         a Document becomes cards: relocation, prompt, schema
atlas/llm.py           one chat client with a disk cache in front of it
atlas/cli.py           argument parsing and file IO; no logic lives here
docs/                  architecture, ontology, evaluation contract
tests/                 one file per module; fixtures are generated, never committed as binaries
```

A stage is a function from artifacts to artifacts. It does not know about a database, a web server or a queue. Storage and IO live at the edge: the CLI reads a file, calls one library function, writes the result.

Adding a stage: put it in its own package under `atlas/`, add its artifact type to `contracts.py`, add `tests/test_<stage>.py`. If a type crosses a package boundary, it belongs in `contracts.py` — that rule is what lets two people work without meeting.

## Commands

```bash
pip install -e ".[dev]"    # once
pytest                     # the whole suite, no network, no API key
ruff check .               # what CI runs
atlas ingest paper.pdf --out markdown/
atlas extract markdown/<id>.md --out cards.jsonl
```

Tests never reach the network and never need a key. A test that would call a model uses a stub with the signature of `Client.complete_json`.

## House rules for code

- Python 3.12, type hints everywhere, `from __future__ import annotations`, pydantic v2.
- Libraries yes; frameworks that dictate the shape of the code no. No LangChain, no LlamaIndex, no RAGAS.
- No abstraction with a single implementation. A protocol arrives with its second implementation, not before.
- Files stay under about 150 lines. Past that, the design is wrong — simplify rather than split arbitrarily.
- A module docstring says what the module is for and why it is shaped that way, in a few lines. Comments inside a function exist only where the code cannot speak: a non-obvious invariant, a deliberate trade-off, a subtle failure mode. Never narrate the next line. No TODO, no commented-out code.
- Neutral English everywhere: code, comments, tests, commit messages. No organisation names, no personal data, no AI attribution.
- Deterministic ids: a content hash of the material that makes the artifact what it is. Re-running over unchanged input must rewrite the same ids.

## Changing the contracts

`atlas/contracts.py` and `atlas/ontology/core.yaml` are the two files everyone depends on.

- Adding a field is free. Renaming or removing one is a breaking change for every stage and for every artifact already written.
- `core.yaml` is byte-hashed into `ontology_version`, so editing it changes the version of every future run and invalidates the prompt cache. Domain vocabulary goes into an extension file, never into the core.
- Both files are changed with the other people on the project knowing, not in passing.

## Where this is going

Direction, so that today's code leaves room for it rather than being redone:

- **Identity.** Every ontology type, predicate and domain term carries an IRI and SKOS mappings to public vocabularies. This is the one thing that cannot be retrofitted cheaply: a label is not an identity.
- **Schema artifacts.** The schema is authored once and SHACL, OWL and JSON Schema are generated from it. SHACL validates cards; a reasoner runs in CI over the schema only, never over extracted data, where an open-world inference would invent the missing spans it is supposed to reject.
- **Storage.** PostgreSQL as the system of record: JSONB for fields that are still moving, full text and vectors in the same engine. RDF and a SPARQL endpoint are a published projection of it, not the working store.
- **Stages not yet written.** Edge extraction; canonicalisation of entities across documents; hybrid retrieval; an answering agent that descends topic to card to exact place; an evaluation harness driven by competency questions with a dev/test split and corrupted negative controls that must drop the metric.

The artifact types for the unwritten stages are already declared in `contracts.py` and unused. That is deliberate: it fixes the shape of the seams. Do not delete them, and do not treat their presence as a claim that the stage exists.

## What not to do

- Do not weaken an invariant to make a test pass. The invariant is the product.
- Do not add a database, a server or a queue inside a stage.
- Do not ask the model for offsets, page numbers as ground truth, or anything you can verify yourself.
- Do not commit binary fixtures, a cache directory, a virtualenv, or anything under `.atlas-cache/`.
- Do not report a metric without the cases behind it. A number that survives a corrupted input is worthless.
