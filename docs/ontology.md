# The ontology

## What the core is

`atlas/ontology/core.yaml` declares six node types (Task, Method, Dataset, Metric,
Result, Claim) and eight predicates between them. It is the frozen part of the
schema: editing it changes the version of every run made afterwards, and is a
decision about the format rather than about a corpus.

It is small for two reasons. A type earns its place only if it is recognisable in
any field that publishes measured work; a type that makes sense in one field alone
would make markup from two fields incomparable, and belongs in an extension. And
the core is shown to the extractor on every page, so fifty types would spend
context on distinctions no reader can draw reliably.

## Every extension type descends from a core type

`load(core_path=None, extension_path=None)` reads the core, reads an optional
extension, and merges them. An extension type must declare a `parent`, and that
parent must already be known when the child is read: a core type, or a type
declared earlier in the same extension file. Forward references are refused, which
also rules out parent cycles, so the ancestor walks in this module terminate.

Descent buys three things. A consumer that knows only the core can read any
extension by folding a type to its nearest core ancestor, which is what keeps two
domains comparable. Fields are inherited along the ancestor chain, so an extension
type declares only what it adds. And core predicates keep working on extension
types, because `domain` and `range` are checked by ancestry rather than by name
equality: a `Method` predicate accepts any descendant of `Method`.

## The shape of an extension file

An extension file has the same two keys as the core, `types` and `predicates`. The
only difference is that `parent` is required on every type.

```yaml
types:
  - name: BrewingSchedule
    parent: Method
    fields: [water_temperature, steep_time]
    description: A timing and temperature plan for preparing an infusion.
```

A predicate takes `name`, `domain`, `range` and an optional `description`; domain
and range may name a core type or an extension type. Type names and predicate
names each live in one flat namespace across both files, and a duplicate is
refused at load time.

## How the version hash works

`Ontology.version` is the first twelve hex characters of the SHA-256 over the raw
bytes of the core file followed by the raw bytes of the extension file. It hashes
bytes, not the parsed structure, so reordering entries or editing a comment yields
a new version. That is intended: the file text is what the extractor is shown.

Every card and every edge carries `ontology_version`. This is what makes markup
written last month still interpretable after this month's edit. You can tell which
schema a card was written under, refuse to merge two runs made under different
schemas, or revalidate old cards against the new ontology and see exactly what the
edit broke. The version is an identity, not a sequence number: it does not say
which of two ontologies is newer.

## Validation reports violations, it does not raise

`validate_card(card, ontology)` and `validate_edge(edge, ontology, src_type,
dst_type)` each return a list of strings; an empty list means valid. They do not
raise, because a run exists to measure the markup it actually produced. Aborting on
the first bad card would throw away the evidence and report nothing.

A broken ontology file does raise: unparsable YAML, an extension type with a
missing or unknown parent, a duplicate name. Those are defects in a hand-written
input, detected before any card exists.

## The metric that matters

The share of cards and edges with at least one violation.

Extracted cards read well one at a time. Fluent field text, a quote that looks like
a quote, a predicate name that sounds right in the sentence. None of that
distinguishes an extraction that works from one that only looks like it. The
violation share is computed against the declared schema instead: a run that invents
type names, puts fields on types that do not declare them, or joins the wrong two
types with a predicate is emitting text shaped like markup that will not answer a
query.

Report it split by artifact (cards, edges) and by violation kind, because the fixes
differ: an unknown type usually means the extension is missing a type, while a
domain mismatch usually means the extraction is wrong. Report it with the offending
cases attached, per `docs/evaluation.md`.
