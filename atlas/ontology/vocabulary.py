"""The IRIs the ontology layer reads, and the substrate's own small vocabulary.

Everything an ontology says about its classes and properties is standard OWL 2, RDFS and
SKOS, and is read as such. Four things a configuration needs are not said by any of those
vocabularies, and are said here instead, as annotation properties -- which OWL reasoners
ignore by definition, so an ontology using them is still exactly the ontology it was:

* `atlas:name` -- the word a configuration, a prompt and a node's `type` use for a term.
  An IRI is the identity; the name is what a person types. Without one the local part of
  the IRI is used, which is fine for `core:Result` and useless for `obo:BFO_0000040`.
* `atlas:fields` -- the ordered list of datatype properties a class's instances carry.
  Not `rdfs:domain`, which in OWL is an inference rule ("anything with a name is a
  Result") and not a declaration of what a Result records.
* `atlas:labelField` -- which of those fields names the thing for a reader.
* `atlas:profile` -- on an ontology, the OWL 2 profile it is written to stay within.

The substrate namespace also names how a node, a link and a span are written as RDF
(`ontologies/atlas.ttl`), which is what the SHACL engine validates and what an export
publishes. None of those terms is ever projected into a schema's vocabulary.
"""

from __future__ import annotations

from rdflib import Namespace
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

ATLAS = Namespace("https://w3id.org/atlas-of-science/substrate#")
"""The substrate's own terms: annotation properties, and the RDF shape of the metamodel."""

HOME = "https://w3id.org/atlas-of-science/"
"""Ontologies whose IRI starts here are ones this library can find without a network:
an `owl:imports` of `<HOME>science_core` resolves to `science_core.ttl` beside the
importing file, or among the shipped ontologies."""

LOCAL = "urn:atlas:local:"
"""The IRI given to a term a legacy pack declared without one. It is never shown: a term
with this IRI projects to a `TypeDef` whose `iri` is None, which is what the pack said."""

OA = Namespace("http://www.w3.org/ns/oa#")
PROV = Namespace("http://www.w3.org/ns/prov#")
SH = Namespace("http://www.w3.org/ns/shacl#")

MATCHES = (SKOS.exactMatch, SKOS.closeMatch, SKOS.broadMatch, SKOS.narrowMatch,
           SKOS.relatedMatch, RDFS.seeAlso, DCTERMS.source)
"""What a term may say it corresponds to elsewhere, strongest first. Read into
`mappings`; a reasoner treats none of them as equivalence, which is the point of SKOS."""

DATATYPES = {
    str(XSD.string): "string", str(XSD.decimal): "number", str(XSD.double): "number",
    str(XSD.float): "number", str(XSD.integer): "integer", str(XSD.boolean): "boolean",
    str(XSD.date): "date", str(XSD.dateTime): "datetime", str(XSD.anyURI): "iri",
}
"""What the range of a datatype property is called in a `FieldDef`."""

PROFILES = ("RDFS", "EL", "QL", "RL", "DL")
"""The profiles an ontology or a configuration may name: RDFS entailment, the three OWL 2
tractable profiles, and OWL 2 DL."""

__all__ = [
    "ATLAS", "DATATYPES", "DCTERMS", "HOME", "LOCAL", "MATCHES", "OA", "OWL", "PROFILES", "PROV",
    "RDF", "RDFS", "SH", "SKOS", "XSD",
]
