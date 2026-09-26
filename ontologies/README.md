# Ontologies

An ontology is OWL 2, written in Turtle, and it is data, not code: the library ships no
vocabulary of its own, so a corpus is read under whatever ontologies a configuration
names. These ship inside the wheel; `atlas.ontology.builtin("science_core")` is the path to
one wherever the library was installed from, and `atlas.ontology.resolve(spec, base)` finds
an ontology beside the configuration that named it, then under the working directory, then
here. An `owl:imports` of one of these is followed the same way.

`atlas.ontology.load(*specs, base=None, profile="", shapes=())` merges them in the order
given into one RDF graph, reads it into OWL 2 axioms and a vocabulary, classifies it with
the OWL 2 EL engine, refuses it if it leaves the named profile, and versions the result by
the sha256 of the bytes read.

## Modules by profile

Each ontology is a **base module** that every tractable profile can read -- the class
hierarchy, the relation signatures, sub-relations and disjoint classes -- and, where it has
more to say, **one module per profile** importing the base:

| module | profile | what it adds | engine |
|---|---|---|---|
| `science_core` | EL, QL, RL | the argument: claim, position, line of evidence, result, conditions, computation | any |
| `science_core_rl` | RL | transitivity, inverses, disjoint relations, property chains, sufficient conditions of the defined classes | rules over data, with derivations |
| `science_core_el` | EL | full definitions with existentials; chains | classification |
| `science_core_ql` | QL | inverses, symmetry, existentials on the right | query rewriting |
| `science_core_dl` | DL | unions, qualified cardinality, universals | the tableau, over the ontology only |
| `process`, `process_rl` | EL/QL/RL, RL | plan against run, conditions, positive and negative results; the chains that carry conditions to results | |
| `science_map`, `science_map_rl` | EL/QL/RL, RL | topics and passages; a thing in a narrow topic is in the broader one | |
| `semantic_units` | EL/QL/RL | the form of a claim | |
| `scierc`, `scierc_rl`, `scierc_ql` | RDFS, RL, QL | SciERC as a local profile; its six labels disjoint | |
| `ml_paper` | RDFS | one domain's ontology, to copy | |
| `fields` | any | the datatype properties every class lists as its fields | |
| `atlas` | -- | the substrate's own vocabulary; never part of a schema | |

The split is the OWL 2 profiles doing their job. Each profile is a guarantee an engine
makes -- RL never invents an individual, EL classifies completely, QL rewrites into a finite
union -- and an ontology that mixed them would be one no engine could fully honour. A
configuration names the modules for its engine and the profile they must stay within.

## What a class and a relation say

Standard OWL 2, RDFS and SKOS, plus four annotation properties from the substrate
vocabulary (`atlas.ttl`) that OWL has no word for:

| | |
|---|---|
| `atlas:name` | the word a configuration, a prompt and a node's `type` use for the term |
| `atlas:fields` | the ordered list of datatype properties an instance records |
| `atlas:labelField` | which of those names the thing for a reader |
| `atlas:inferred` | the class's members are inferred; an extractor is never offered it |

`skos:definition` is the description a prompt shows; `skos:closeMatch` and the other SKOS
mapping properties are what a term corresponds to elsewhere, and no engine treats them as
equivalence.

## Shapes

`shapes/` holds SHACL: what a record must carry, checked in closed world. OWL says what
follows from a record; it cannot say what a record must hold. A configuration names the
shapes it applies with `schema: {shapes: [...]}`, and the shapes' bytes are part of the
schema version.

## Writing one

Copy `ml_paper.ttl`, keep one domain per file, import `fields` for the common fields, and
mint the IRIs under a namespace you control -- a label is local to an ontology, an identity
outlives it. Protégé opens every file here; save back as Turtle so it diffs.

A legacy YAML pack still loads, and is imported into the same OWL layer as the axioms it
states. See `docs/ontology.md`.
