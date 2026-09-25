# The ontology

An ontology here is **OWL 2**, written in Turtle, and it is the working layer of the library:
every configuration names one, every step reads the vocabulary it projects, and five engines
reason over its axioms. This document says what an ontology file holds, how it is loaded, which
engine reads which part of it and why, and how SHACL covers what OWL cannot.

## There is no core

The library ships no vocabulary. `atlas.ontology.load()` with nothing to load returns an empty
schema, and every class a corpus uses arrives from an ontology named in a configuration. Nothing
under `atlas/` mentions a class, a field or a relation of any domain, and `tests/test_substrate.py`
runs the shipped steps over an invented one to keep it that way.

The ontologies under `ontologies/` ship with the library as data to start from:
`atlas.ontology.builtin("science_core")` is the path to one wherever the library was installed from.

## What an ontology file holds

Standard OWL 2 in RDF — classes, object properties, datatype properties and axioms — plus four
annotation properties from the substrate vocabulary (`ontologies/atlas.ttl`) for what OWL has no
word for. Annotation properties are ignored by every OWL reasoner by definition, so using them
changes nothing about what the ontology means.

```turtle
@prefix obs:   <https://example.org/ontology/observation#> .
@prefix field: <https://w3id.org/atlas-of-science/fields#> .
@prefix atlas: <https://w3id.org/atlas-of-science/substrate#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos:  <http://www.w3.org/2004/02/skos/core#> .

<https://example.org/ontology/observation>
    a owl:Ontology ;
    owl:imports <https://w3id.org/atlas-of-science/fields> ;
    atlas:profile "RL" .

obs:Observation a owl:Class ;
    atlas:name "Observation" ;
    skos:definition "Something recorded as having happened, at a place and a time." ;
    atlas:fields ( field:name field:value ) ;
    atlas:labelField field:name .

obs:SpectralObservation a owl:Class ;
    atlas:name "SpectralObservation" ;
    rdfs:subClassOf obs:Observation ;
    skos:closeMatch <https://schema.org/Observation> .

obs:recordedWith a owl:ObjectProperty ;
    atlas:name "recorded_with" ;
    rdfs:domain obs:Observation ;
    rdfs:range obs:Instrument .
```

| | |
|---|---|
| `atlas:name` | The word a configuration, a prompt and a node's `type` use for a term. Without one, the local part of the IRI is used — fine for `obs:Observation`, useless for `obo:BFO_0000040`. Two IRIs claiming one name are refused. |
| `atlas:fields` | The ordered list of datatype properties an instance records: what a prompt asks for and what a closed SHACL shape allows. Not `rdfs:domain`, which in OWL is an inference ("anything with a name is an Observation"), not a declaration. |
| `atlas:labelField` | Which field names the thing for a reader. |
| `atlas:inferred` | The class's members are whatever the axioms make them. An engine infers them; an extractor is never offered the class. |

`skos:definition` is what the extractor is shown, so it is written for a reader who has never seen
the ontology. `skos:closeMatch` and the other SKOS mapping properties are what a term corresponds to
elsewhere; no engine treats them as equivalence, which is the point of SKOS.

The fields every ontology uses are declared once, in `ontologies/fields.ttl`, and imported: a
field is a slot of a node and a node's fields are keyed by name, so two IRIs for `name` would be
one slot with two identities, and an export could not say which it was. The one case for a second
property under a name is a second datatype — a datatype property has one range — and a legacy pack
whose class narrows an inherited field to a date gets that property without asking: its local IRI
is keyed by name and datatype (`atlas.ontology.vocabulary.local_field`), and the nearest
declaration wins, as it always did.

## How an ontology is loaded

`load(*specs, base=None, profile="", shapes=())` does five things, in order.

1. **Each file is read in the format its suffix names** — Turtle, RDF/XML (`.owl`, what Protégé
   writes by default), JSON-LD, N-Triples, or a legacy YAML pack. An `owl:imports` of one of this
   library's ontologies is followed, beside the importing file first and then among the shipped
   ones; an import from anywhere else is recorded in `Schema.imports` and not fetched. Nothing
   reaches the network.
2. **The files become one RDF graph**, and every IRI in it is given one name, so a class declared
   in one file is the parent of a class in another.
3. **The graph is read into OWL 2 axioms** (`atlas.model.owl`, the structural specification's
   model) and into the vocabulary a configuration reads — one `TypeDef` per declared class, one
   `PredicateDef` per object property. What no engine models (data ranges, nominals) comes back in
   `Schema.unread` by the triple that states it, never silently dropped.
4. **The axioms are classified** by the OWL 2 EL engine, and `Schema.hierarchy` holds every named
   superclass of every class. `Schema.is_a` answers from it, so a class an equivalence or an
   existential restriction makes a subclass is one without anybody writing it as a parent.
5. **The profile is enforced.** A configuration that names one gets an ontology inside it, or a
   `ValueError` naming the axioms that are not.

`load_text(*contents)` does the same for ontologies held as content, for a consumer that keeps them
in a database. `atlas.ontology.to_turtle(schema)` writes a schema back out; the round trip preserves
every axiom an engine reasons with, and `tests/test_ontology.py` holds that.

## Profiles, and the engine for each

OWL 2 defines three tractable profiles (W3C, *OWL 2 Profiles*, 2012). Each exists because of what
an engine can then guarantee, and this library has an engine for each, plus one for RDFS entailment
and a tableau for the whole of OWL 2 DL:

| profile | engine | runs over | what it guarantees |
|---|---|---|---|
| RDFS | `atlas.reason.rl`, four rules | the data | types by domain, range, subclass, sub-property |
| RL | `atlas.reason.rl` | the data | every consequence with its derivation, every clash, and **no individual invented** |
| EL | `atlas.reason.el` | the ontology | the complete class hierarchy, in polynomial time |
| QL | `atlas.reason.ql` | a query | the certain answers, by rewriting into plain joins over what is stored |
| DL | `atlas.reason.tableau` | the ontology | whether it has a model, and whether each class can have members |

`atlas.reason.profile.outside(axioms, profile)` returns the axioms that break a profile's contract,
and every profile is also held to OWL 2 DL's global restrictions: a transitive relation is never
also irreflexive, whatever a profile's own grammar allows.

### Why only RDFS and RL run over data

This is the rule the whole layer is built around, and it is what lets reasoning coexist with the
first invariant — *no provenance, no node*.

**No rule of OWL 2 RL invents an individual.** An existential on the right of an axiom — "every
result was obtained under some condition" — is not expressible in the profile, so no rule can
conclude that a condition exists that nobody mentioned. Everything the RL engine derives relates
individuals that were already there, each derived fact stands on facts that each stand on a quote,
and each carries its derivation: the rule, in the OWL 2 RL rule table's own name (`prp-trp`,
`cax-sco`, `cls-svf`), the facts it came from, and the axiom that licensed it. A derived link
carries the spans of its premises rather than one of its own, and is marked derived.

EL, QL and DL can all conclude that something exists without naming it. So they are never run to
materialise anything: EL and DL are asked about the ontology, and QL answers a query by rewriting,
returning only rows that are stored.

### Modules by profile

The shipped ontologies are therefore split. Each has a **base module** that every tractable profile
can read — the class hierarchy, relation signatures, sub-relations, disjoint classes — and, where it
has more to say, **one module per profile** importing the base: `science_core_rl` adds
transitivity, inverses, disjoint relations, property chains and the sufficient conditions of the
defined classes; `science_core_el` adds full definitions with existentials; `science_core_ql` adds
inverses and existentials on the right; `science_core_dl` adds unions, qualified cardinalities and
universals. `ontologies/README.md` lists them all.

This is not duplication. Each profile is a guarantee an engine makes, and an ontology that mixed
them would be one no engine could fully honour. Every module declares the profiles it is written
for (`atlas:profile`), and `tests/test_ontologies.py` checks each one, with its imports, against
each profile it declares — and runs the tableau over it to show it is consistent with every class
able to have members.

## Naming an ontology in a configuration

`schema` is a name, a list of names, or a mapping that also names the profile and the shapes:

```yaml
schema:
  ontologies: [science_core_rl, scierc_rl]
  profile: RL
  shapes: [science_core, critic]
```

The profile is a contract: the configuration's engines are complete for it, and an ontology that
leaves it is refused when the file is read. The shapes are part of the schema — their bytes are in
its version — because a record validated against different shapes is a different record.

## Shapes: what OWL cannot say

OWL says what follows. It cannot say what must be there: under the open-world assumption a node
with no `observed_under` is not a node without conditions, it is one whose conditions nobody
mentioned, and no reasoner will complain. That is the right reading for inference and the wrong one
for a record about to be relied on. So the record is validated by **SHACL** (`atlas.reason.shacl`,
with pySHACL), in closed world, against two sets of shapes:

- **the shapes the ontology implies**, generated: each class's own fields and nothing else (a closed
  shape), every node on at least one span, and each relation's domain and range as a closed-world
  `sh:class` — the subject of `supports` must already be an EvidenceLine, not become one by
  inference;
- **the shapes a configuration names**, hand-written under `ontologies/shapes/`: a computation that
  depends on its own output through a chain (which OWL 2 DL cannot state of a transitive relation), a
  statement on two propositions, a result with no conditions.

A violation refuses the object; a warning is recorded beside it and the object is kept. A domain or
range check refuses the *relation*, not the node at its end: the node may be exactly what it says it
is, and the relation the thing that was misread. `shacl_validate` runs before `assert`, reads a node
already in the store as context when a relation reaches it, and never refuses what is stored.
Validation runs with inference switched off: reasoning is the engines' job, and a validator that
inferred as it validated would pass a node for being what it was only inferred to be.

## The engines in the steps

An engine is a library under `atlas/reason/`; a step runs it, and a configuration names the step.

| step | engine | what it does with the ontology |
|---|---|---|
| `entail` | RL, or RDFS with `engine: rdfs` | closes the stored graph under the rules; `derived`, `typings`, `identities` and `clashes`, each with its derivation. `identity: [same_as]` gives a relation the meaning of `owl:sameAs` |
| `classify` | EL, or the tableau with `engine: dl` | the hierarchy, the empty classes, and what the engine could not read |
| `formal_check` | EL or the tableau | the gate a build chain starts with: cycles, empty classes, unknown terms, axioms outside the profile, an ontology with no model |
| `shacl_validate` | SHACL | the record against the generated and the named shapes, before it is asserted |
| `query` | QL | a conjunctive query, rewritten and answered over the store, the answers walked into a package |
| `graph_expand_sql`, `execute_plan` | QL | the relations and classes a configuration or a plan names, rewritten before any SQL is written; the plan's trace records each rewriting |
| `compile_units` | EL | an exact semantic unit as an axiom -- "all S are O" is `SubClassOf(S, O)` -- and the units that together leave a term with no possible member |
| `promote` | EL | a proposal written as an OWL module, loaded and classified with the run's ontology before anybody reads it |

The steps that read relations by name -- every selection step, `compare`, `lineage`, `align`,
`reconcile` -- widen them with the QL rewriting of one relation and read the links an `entail` step
derived, so a configuration that names `observed_under` also reaches `obtained_under`, which the
process ontology declares a kind of it and derives through a property chain. Which of those links
nobody claimed stays visible all the way to the answer.

## Identity, not labels

A name is local to one schema; an IRI outlives it. Lookup accepts either:
`find_type("Observation")`, `find_type("obs:Observation")` and the full IRI are the same class, and
`is_a("SpectralObservation", "obs:Observation")` is true. This is what lets two ontologies be
compared without descending from a common ancestor: "these two classes are the same" is an identity,
not a position in a tree. The shipped ontologies use the real IRIs of BFO, IAO, OBI, ECO, SIO, EVI
and SEPIO for their classes, checked against the published ontologies, and local IRIs with a
`skos:closeMatch` wherever an external IRI was not verified.

## How the version hash works

`Schema.version` is the first twelve hex characters of the SHA-256 over the raw bytes of every file
loaded — ontologies in load order, imports before the file that imports them, then shapes. It hashes
bytes, not the parsed structure, so editing a comment yields a new version. That is intended: the
text is what the extractor is shown.

Every node and every link carries that version as `schema_version`, and a `Schema` carries its
axioms and its classified hierarchy, so an object written last month stays interpretable after this
month's edit — including what the ontology implied about it.

## Validation reports violations, it does not raise

`Schema.validate_node` and `Schema.validate_link` return a list of strings, and a SHACL report is a
list of findings; neither raises, because a run exists to measure the markup it actually produced.
A broken ontology does raise — an unparsable file, a name two IRIs claim, an ontology outside the
profile its configuration names. Those are defects in a hand-written input, detected before any node
exists.

## Legacy YAML packs

A pack — `prefixes`, `types` with `parent`, `fields`, `disjoint_with`, and `predicates` with
`domain`, `range`, `characteristics`, `inverse_of` — still loads. It is read by writing it into the
same RDF graph an ontology file is parsed into (`atlas.ontology.yaml_pack`), and from there it is the
same ontology as any other, reasoned over by the same engines. Its rules are kept exactly — a key the
model does not declare is refused, a pack with prefixes must identify every term, a parent must
resolve — and a schema loaded from packs alone hashes exactly as it always did, so a consumer's
stored versions do not move. A pack cannot say what an ontology file can: defined classes,
restrictions, chains, disjoint relations.

## Writing one

Copy `ontologies/ml_paper.ttl`, keep one domain per file, import `fields` for the common fields,
and mint the IRIs under a namespace you control. Protégé opens every file here; save back as Turtle
so it diffs. Decide which profile each axiom belongs to before writing it: a sufficient condition is
RL, a necessary one with an existential is EL, and the moment a union appears on the right, the axiom
belongs in a DL module that no engine runs over data.

## The metric that matters

The share of nodes and links with at least one violation, and — with an RL engine configured — the
number of clashes.

Extracted nodes read well one at a time. None of that distinguishes an extraction that works from one
that only looks like it. The violation share is computed against the declared ontology instead, and a
clash is the ontology proving two extracted claims cannot both be true. Report both split by kind,
with the offending cases attached, per `docs/evaluation.md`.
