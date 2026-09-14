# Packs

A pack is one YAML file of ontology -- `prefixes`, `types`, `predicates` -- and it is data, not code: the library ships no vocabulary of its own, so a corpus is read under whatever packs are named on the command line.

These packs ship inside the wheel: `atlas.ontology.builtin("ml_paper")` is the path to one wherever the library was installed from, and `atlas.ontology.resolve(spec, base)` finds a pack beside the configuration that named it, then under the working directory, then here.

`atlas.ontology.load(*specs, base=None)` merges packs in the order given and versions the result by the sha256 of their bytes, which is the version every node and link then carries.

A type declares `name`, `iri`, an optional `parent` whose fields it inherits, its own `fields` (a bare name, or a mapping with `datatype` and `iri`), the `label_field` that names which of them names the thing, optional `mappings` to public vocabularies, and a `description`; a predicate declares `name`, `iri`, `domain`, `range` and a `description`.

Declaring `prefixes` makes an `iri` compulsory on every type and predicate of that file, and any IRI there may be written as a CURIE against those prefixes; every `parent`, `domain` and `range` must resolve within the merged packs, and a name declared twice is an error.

To write one, copy `ml_paper.yaml`, keep one domain per file, and mint the IRIs under a namespace you control -- a label is local to a pack, an identity outlives it.
