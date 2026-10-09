"""String-backed property graph values retain schema datatypes in the RDF projection."""

from rdflib import Literal
from rdflib.namespace import XSD

from atlas.model import FieldDef, Node, Schema, TypeDef
from atlas.ontology.abox import field_iri, node_iri, to_graph
from atlas.reason.shacl import validate
from tests.test_shacl import span


def test_declared_inherited_datatypes_preserve_original_lexical_values():
    fields = tuple(FieldDef(name=name, datatype=datatype) for name, datatype in (
        ("amount", "number"), ("count", "integer"), ("flag", "boolean"),
        ("day", "date"), ("time", "datetime"), ("uri", "iri"), ("text", "string")))
    schema = Schema(version="v", types=(TypeDef(name="Parent", fields=fields),
                           TypeDef(name="Child", parent="Parent")))
    original = {"amount": "01.00", "count": "02", "flag": "true", "day": "2026-10-09",
                "time": "2026-10-09T00:00:00Z", "uri": "https://example.org/a", "text": "01"}
    node = Node(id="n", type="Child", fields=original, spans=span(0, 6), schema_version="v")
    graph = to_graph(schema, (node,))
    for name, datatype in (("amount", XSD.decimal), ("count", XSD.integer),
                           ("flag", XSD.boolean), ("day", XSD.date), ("time", XSD.dateTime),
                           ("uri", XSD.anyURI), ("text", None)):
        assert (node_iri(node.id), field_iri(schema, node.type, name),
                Literal(original[name], datatype=datatype, normalize=False)) in graph
    assert node.fields == original


def test_decimal_shape_admits_valid_original_and_refuses_invalid_lexical_value():
    schema = Schema(version="v", types=(TypeDef(name="Value", fields=(FieldDef(name="amount",
                    datatype="number", iri="urn:test:amount"),), iri="urn:test:Value"),))
    shape = '''@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<urn:test:shape> a sh:NodeShape; sh:targetClass <urn:test:Value>;
sh:property [sh:path <urn:test:amount>; sh:datatype xsd:decimal] .'''
    def record(value):
        return Node(id="n", type="Value", fields={"amount": value}, spans=span(0, 6),
                    schema_version="v")
    assert validate(schema, (record("01.00"),), shapes=shape).conforms
    assert validate(schema, (record("not numeric"),), shapes=shape).refused() == {"n"}
