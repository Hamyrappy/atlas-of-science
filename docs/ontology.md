# The ontology

## There is no core

The library ships no vocabulary. `atlas.ontology.load()` with nothing to load returns an empty
schema — no types, no predicates — and every type a corpus uses arrives from a pack named in a
configuration file. Nothing under `atlas/` mentions a type, a field or a predicate of any domain,
and `tests/test_substrate.py` runs the shipped steps over an invented one to keep it that way.

This was not always so. Six machine-learning types used to be built into the library as a core
that every other type had to descend from. They now live in `packs/ml_paper.yaml` as one domain's
pack among others, loaded only when a configuration asks for it. A core buys comparability between
two domains and charges for it in every domain that does not fit; identity, below, buys the same
thing without the tax.

## What a pack declares

A pack is one YAML file with three optional keys: `prefixes`, `types`, `predicates`.

```yaml
prefixes:
  obs: https://example.org/ontology/observation#
  schema: https://schema.org/

types:
  - name: Observation
    iri: obs:Observation
    description: Something recorded as having happened, at a place and a time.
    fields: [subject, value]
    label_field: subject

  - name: SpectralObservation
    iri: obs:SpectralObservation
    parent: Observation
    mappings: [schema:Observation]
    fields:
      - name: wavelength
        datatype: number
        iri: obs:wavelength

  - name: Instrument
    iri: obs:Instrument
    description: A device a recording was taken with.
    fields: [name]

predicates:
  - name: recorded_with
    iri: obs:recordedWith
    domain: Observation
    range: Instrument
    description: The observation was taken with this instrument.
```

A field is a bare name, or a mapping declaring `datatype` and `iri`; that shorthand is the only
sugar in the loader. `label_field` names the field that names the thing, which is what
`Schema.label_of(node)` shows a reader and what an interface prints on a card; a type that omits it
is shown by the first field it declares, and a child inherits its parent's choice. Field order is
then an ordering and nothing more: nothing else in the library reads meaning into it.
`description` is what the extractor is shown, so it is written for a reader
who has never seen the pack. `mappings` are identities in somebody else's vocabulary and are
stored verbatim, never expanded: guessing what a foreign CURIE means against a local prefix map
would be the same guess made twice.

## Where a pack is found

`load(*specs, base=None)` resolves each spec through `atlas.ontology.resolve`, which looks beside
the file that named the pack (`base`, the directory of the configuration), then under the working
directory, and finally among the packs shipped with the library. So several configurations in a
subdirectory can share one pack at the root of a corpus without `../` in every one of them, and a
configuration that says `schema: ml_paper` gets `atlas.ontology.builtin("ml_paper")`, the pack that
travels inside the wheel. `builtin(name)` returns its path, to copy, to load, or to start a pack of
your own from; a consumer's own packs should be package data in the same way, or `pip install` will
give it a loader and no vocabulary.

## Identity, not labels

A name is local to one pack; an IRI outlives it. A pack that declares `prefixes` is claiming
identities, so the loader requires an `iri` on every type and every predicate in it. CURIEs are
expanded against the prefixes of **their own file**, before the merge, so a term means what its
file said even when another pack redeclares the prefix.

Lookup then accepts either form: `find_type("Observation")`, `find_type("obs:Observation")` and
`find_type("https://example.org/ontology/observation#Observation")` are the same type, and
`is_a("SpectralObservation", "obs:Observation")` is true. A node may carry its type as a name or as
an IRI; validation resolves both. This is what lets two packs be compared without either of them
descending from a common ancestor: the claim "these two types are the same" is an identity, not a
position in a tree.

## Parents and inheritance

`parent` is optional. A type that declares one inherits its fields — own fields first, then the
parent's, without repeats — and satisfies any predicate whose `domain` or `range` names an
ancestor: a `recorded_with` that expects an `Observation` accepts a `SpectralObservation`. The
parent may be declared anywhere in the merged packs, before or after the child; what is refused is
a parent that resolves nowhere. A cycle between two parents is not refused at load time, but the
ancestor walk terminates on one rather than hanging.

## Axioms a pack may declare

Beyond names and fields, a pack may say three things that something executes.

`disjoint_with` on a type names the types nothing may be both of. It is inherited downwards, so
declaring it once on a pair of roots covers every pair of leaves under them, and it is an axiom
rather than a hint: `formal_check` fails a release whose type descends from something it is
declared disjoint from, **with no instance required**, because the first instance would be a node
that cannot exist. `science_core.yaml` declares `MaterialEntity`, `Process` and
`InformationEntity` pairwise disjoint, which is the BFO bridge written as something a gate can
fail on -- a file of instructions is not the procedure being carried out, and neither is a sample.

`characteristics` on a predicate names how the relation behaves, and there are exactly two:
`transitive` and `symmetric`. Two, because those are the ones a closure can compute without either
a reasoner or a decision about what to do when it fails to terminate; a pack naming a third is
told so by name rather than having the word accepted and ignored.

`inverse_of` names the predicate that is this one read the other way. A pack states the pair once,
on whichever of the two it was natural to write it on, and both directions answer -- otherwise
half of every inverse would be derivable and the other half silently not.

What executes them is `atlas/steps/entail.py`, and what checks them is
`atlas/steps/formal_check.py`. Neither reads a node: the check runs over the schema and never over
extracted data, where an open-world inference would invent the missing spans the markup layer
exists to refuse.

## Merging several packs

`load(*paths)` merges in the order given: prefix maps are merged with the later pack winning a
repeated prefix, and types and predicates are concatenated. A type name or a predicate name
declared twice is an error — the flat namespace is what makes a bare name usable at all. Splitting
a vocabulary across files is therefore free, and a corpus that needs a general pack plus a local
extension names both.

## How the version hash works

`Schema.version` is the first twelve hex characters of the SHA-256 over the raw bytes of every pack
loaded, concatenated in the order given. It hashes bytes, not the parsed structure, so reordering
entries or editing a comment yields a new version, and naming the same two packs in the other order
yields another. That is intended: the file text is what the extractor is shown.

Every node and every link carries that version as `schema_version`. This is what makes markup
written last month still interpretable after this month's edit. You can tell which packs an object
was written under, refuse to merge two runs made under different ones, or revalidate old objects
against the new schema and see exactly what the edit broke. The version is an identity, not a
sequence number: it does not say which of two schemas is newer.

## Validation reports violations, it does not raise

`Schema.validate_node(node)` and `Schema.validate_link(link, src_type, dst_type)` each return a
list of strings; an empty list means valid. They do not raise, because a run exists to measure the
markup it actually produced — the `validate` step keeps what the schema accepts, carries the rest
of the violations forward in the state, and the run reports both counts. Aborting on the first bad
node would throw away the evidence and report nothing.

A broken pack does raise: unparsable YAML, a pack that is not a mapping, an unknown parent, a
duplicate name, a prefixed pack whose term declares no IRI, a key nobody declared. Those are
defects in a hand-written input, detected before any node exists.

## The metric that matters

The share of nodes and links with at least one violation.

Extracted nodes read well one at a time. Fluent field text, a quote that looks like a quote, a
predicate name that sounds right in the sentence. None of that distinguishes an extraction that
works from one that only looks like it. The violation share is computed against the declared schema
instead: a run that invents type names, puts fields on types that do not declare them, or joins the
wrong two types with a predicate is emitting text shaped like markup that will not answer a query.

Report it split by kind of object and by kind of violation, because the fixes differ: an unknown
type usually means the pack is missing a type, while a domain mismatch usually means the extraction
is wrong. Report it with the offending cases attached, per `docs/evaluation.md`.
