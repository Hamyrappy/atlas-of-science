"""Loading tests: what an ontology becomes, how several merge, and what a bad one raises.

Every class here comes from a file the test names. The core ships none, so `load()` with
nothing named is the empty schema; the six machine-learning classes live in
`ontologies/ml_paper.ttl` like any other domain's and are loaded explicitly -- shipped with
the library as data to start from, never as a vocabulary the core knows.

A legacy YAML pack is still read, into the same OWL layer, and the rules a pack was held
to are held here: `LEGACY` is the machine-learning pack as it was written before the
ontologies moved to Turtle, and it loads to the same vocabulary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.model import Node, Span
from atlas.ontology import builtin, load, load_text, resolve, to_turtle

ONTOLOGY = Path(__file__).parents[1] / "ontologies" / "ml_paper.ttl"
NAMESPACE = "https://example.org/ontology/ml-paper#"

LEGACY = """
prefixes:
  ml: https://example.org/ontology/ml-paper#
  schema: https://schema.org/
  dcat: http://www.w3.org/ns/dcat#
types:
  - {name: Task, iri: ml:Task, fields: [name, definition], label_field: name}
  - {name: Method, iri: ml:Method, fields: [name, summary], label_field: name}
  - {name: Dataset, iri: ml:Dataset, mappings: [schema:Dataset, dcat:Dataset],
     fields: [name, description], label_field: name}
  - {name: Metric, iri: ml:Metric, fields: [name, unit], label_field: name}
  - {name: Result, iri: ml:Result, fields: [statement, value, conditions]}
  - {name: Claim, iri: ml:Claim, fields: [statement, scope]}
predicates:
  - {name: addresses, iri: ml:addresses, domain: Method, range: Task}
  - {name: evaluated_on, iri: ml:evaluatedOn, domain: Method, range: Dataset}
  - {name: measured_by, iri: ml:measuredBy, domain: Result, range: Metric}
  - {name: obtained_by, iri: ml:obtainedBy, domain: Result, range: Method}
  - {name: reported_for, iri: ml:reportedFor, domain: Result, range: Dataset}
  - {name: supports, iri: ml:supports, domain: Result, range: Claim}
  - {name: contradicts, iri: ml:contradicts, domain: Result, range: Claim}
  - {name: extends, iri: ml:extends, domain: Method, range: Method}
"""

SECOND = """
types:
  - name: Assay
    parent: Method
    fields: [protocol]
predicates:
  - name: calibrated_with
    domain: Assay
    range: Dataset
"""


def write(tmp_path: Path, body: str, name: str = "second.yaml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def node(type_name: str, fields: dict[str, str]) -> Node:
    text = "a verbatim fragment"
    span = Span(source_id="src-1", segment=1, start=0, end=len(text), text=text)
    return Node(id="node-1", type=type_name, fields=fields, spans=(span,), schema_version="0" * 12)


def test_the_core_ships_no_vocabulary() -> None:
    empty = load()
    assert empty.types == () and empty.predicates == ()
    assert len(empty.version) == 12


def test_a_pack_is_loaded_only_when_it_is_named() -> None:
    schema = load(ONTOLOGY)
    assert schema.type_names() == {"Task", "Method", "Dataset", "Metric", "Result", "Claim"}
    assert len(schema.predicates) == 8
    assert schema.find_predicate("evaluated_on") is not None
    assert schema.version != load().version


def test_a_term_is_found_by_its_name_its_iri_or_its_curie() -> None:
    schema = load(ONTOLOGY)
    task = schema.find_type("Task")
    assert task is not None and task.iri == f"{NAMESPACE}Task"
    assert schema.find_type(f"{NAMESPACE}Task") is task
    assert schema.find_type("ml:Task") is task
    assert set(schema.find_type("Dataset").mappings) == {"schema:Dataset", "dcat:Dataset"}


def test_a_legacy_pack_loads_to_the_same_vocabulary_as_the_ontology(tmp_path: Path) -> None:
    """The pack is read into the same OWL layer, so the two are one vocabulary."""
    legacy = load(write(tmp_path, LEGACY, "ml_paper.yaml"))
    owl = load(ONTOLOGY)
    assert legacy.type_names() == owl.type_names()
    assert {(p.name, p.domain, p.range) for p in legacy.predicates} == {
        (p.name, p.domain, p.range) for p in owl.predicates}
    assert legacy.find_type("Dataset").mappings == ("schema:Dataset", "dcat:Dataset")
    assert legacy.version != owl.version


def test_the_version_is_the_hash_of_the_bytes_loaded(tmp_path: Path) -> None:
    second = write(tmp_path, SECOND)
    assert load(ONTOLOGY).version == load(ONTOLOGY).version
    assert load(ONTOLOGY, second).version != load(ONTOLOGY).version
    assert load(ONTOLOGY, second).version != load(second, ONTOLOGY).version
    assert len(load(ONTOLOGY, second).version) == 12


def test_packs_merge_and_a_child_inherits_across_the_seam(tmp_path: Path) -> None:
    schema = load(ONTOLOGY, write(tmp_path, SECOND))
    assay = schema.find_type("Assay")
    assert assay is not None and assay.parent == "Method"
    inherited = [field.name for field in schema.declared_fields("Assay")]
    assert inherited == ["protocol", "name", "summary"]
    assert schema.validate_node(node("Assay", {"protocol": "step one", "name": "an assay"})) == []
    assert schema.is_a("Assay", "Method")


def test_a_field_may_be_a_bare_name_or_a_mapping(tmp_path: Path) -> None:
    body = (
        "types:\n  - name: Run\n    fields:\n"
        "      - name\n      - {name: seconds, datatype: number}\n"
    )
    run = load(write(tmp_path, body)).find_type("Run")
    assert [(f.name, f.datatype) for f in run.fields] == [("name", "string"), ("seconds", "number")]


def test_an_unresolved_parent_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, "types:\n  - name: Assay\n    parent: Instrument\n")
    with pytest.raises(ValueError, match="Instrument"):
        load(ONTOLOGY, path)


def test_a_parent_may_be_declared_after_its_child(tmp_path: Path) -> None:
    body = "types:\n  - name: Assay\n    parent: Instrument\n  - name: Instrument\n"
    assert load(write(tmp_path, body)).is_a("Assay", "Instrument")


def test_a_duplicate_name_is_rejected(tmp_path: Path) -> None:
    types = write(tmp_path, "types:\n  - name: Method\n", "dup_type.yaml")
    with pytest.raises(ValueError, match="Method"):
        load(ONTOLOGY, types)
    predicates = write(
        tmp_path,
        "predicates:\n  - name: supports\n    domain: Task\n    range: Claim\n",
        "dup_predicate.yaml",
    )
    with pytest.raises(ValueError, match="supports"):
        load(ONTOLOGY, predicates)


def test_a_pack_that_declares_prefixes_must_identify_every_term(tmp_path: Path) -> None:
    prefixes = "prefixes:\n  ex: https://example.org/x#\n"
    with pytest.raises(ValueError, match="Assay"):
        load(write(tmp_path, prefixes + "types:\n  - name: Assay\n", "type.yaml"))
    with pytest.raises(ValueError, match="calibrated_with"):
        load(
            write(
                tmp_path,
                prefixes + "predicates:\n  - name: calibrated_with\n    domain: A\n    range: B\n",
                "predicate.yaml",
            )
        )


def test_a_pack_that_is_not_a_mapping_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mapping"):
        load(write(tmp_path, "- name: Assay\n"))


def test_an_undeclared_key_in_a_pack_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="colour"):
        load(write(tmp_path, "types:\n  - name: Assay\n    colour: red\n"))


def test_an_ontology_shipped_with_the_library_is_found_by_name() -> None:
    assert builtin("ml_paper") == ONTOLOGY
    assert load("ml_paper").version == load(ONTOLOGY).version
    with pytest.raises(FileNotFoundError, match="wildlife"):
        builtin("wildlife")


def test_a_pack_is_found_beside_the_file_that_named_it_or_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The layout a corpus wants: configurations in a subdirectory naming a pack that
    is not beside them, and no `../` written into every one of them."""
    pack = write(tmp_path, SECOND, "pack.yaml")
    (tmp_path / "configs").mkdir()

    assert resolve("pack.yaml", tmp_path) == pack
    assert resolve(pack) == pack
    monkeypatch.chdir(tmp_path)
    assert resolve("pack.yaml", tmp_path / "configs") == Path("pack.yaml")
    assert load(ONTOLOGY, "pack.yaml", base=tmp_path / "configs").find_type("Assay") is not None


def test_a_pack_that_is_nowhere_says_where_it_was_looked_for(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="corpus/pack.yaml"):
        resolve("corpus/pack.yaml", tmp_path)


# ---- OWL in Turtle ------------------------------------------------------------------------

HEADER = """
@prefix ex:    <https://example.org/x#> .
@prefix atlas: <https://w3id.org/atlas-of-science/substrate#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
<https://example.org/x> a owl:Ontology .
"""


def test_content_loads_exactly_as_the_file_it_came_from() -> None:
    """A consumer that keeps ontologies in a database gets the same schema and version."""
    from_file = load(ONTOLOGY)
    from_content = load_text(ONTOLOGY.read_bytes())
    assert from_content.type_names() == from_file.type_names()
    assert len(from_content.axioms) == len(from_file.axioms)


def test_an_import_of_a_shipped_ontology_is_followed() -> None:
    schema = load("science_core_rl")
    assert schema.find_type("StudyResult") is not None
    assert schema.find_predicate("part_of").characteristics == ("transitive",)
    assert schema.iri.endswith("science_core_rl")


def test_an_import_from_elsewhere_is_recorded_and_not_fetched(tmp_path: Path) -> None:
    body = HEADER + ("<https://example.org/x> owl:imports "
                     "<http://purl.obolibrary.org/obo/bfo.owl> .\n")
    schema = load(write(tmp_path, body, "x.ttl"))
    assert schema.imports == ("http://purl.obolibrary.org/obo/bfo.owl",)


def test_a_configuration_that_names_a_profile_gets_an_ontology_inside_it() -> None:
    assert load("science_core_ql", profile="QL").profile == "QL"
    with pytest.raises(ValueError, match="outside OWL 2 QL"):
        load("science_core_rl", profile="QL")


def test_two_iris_may_not_claim_one_name(tmp_path: Path) -> None:
    body = HEADER + ('ex:A a owl:Class ; atlas:name "Thing" .\n'
                     'ex:B a owl:Class ; atlas:name "Thing" .\n')
    with pytest.raises(ValueError, match="duplicate name 'Thing'"):
        load(write(tmp_path, body, "x.ttl"))


def test_what_no_engine_models_is_named_rather_than_dropped(tmp_path: Path) -> None:
    body = HEADER + ("ex:v a owl:DatatypeProperty .\n"
                     "ex:A a owl:Class ; rdfs:subClassOf [ a owl:Restriction ;"
                     " owl:onProperty ex:v ; owl:someValuesFrom xsd:decimal ] .\n")
    schema = load(write(tmp_path, body, "x.ttl"))
    assert len(schema.unread) == 1 and "datatype property" in schema.unread[0]


def test_a_defined_class_is_classified_and_never_offered_to_an_extractor() -> None:
    from atlas.steps.extract_llm import _catalogue

    schema = load("science_core_el")
    assert schema.find_type("SupportingLine").defined
    assert "SupportingLine" not in _catalogue(schema)
    assert schema.is_a("SupportingLine", "InformationEntity")


def test_the_vocabulary_reads_in_the_order_the_file_declares_it() -> None:
    names = [one.name for one in load(ONTOLOGY).types]
    assert names == ["Task", "Method", "Dataset", "Metric", "Result", "Claim"]


def test_a_schema_written_as_turtle_reads_back_to_the_same_axioms() -> None:
    """The writer is the reader run backwards: nothing an engine reasons with is lost."""

    for name in ("science_core_dl", "science_map_rl", "scierc_rl"):
        schema = load(name)
        again = load_text(to_turtle(schema))
        assert set(again.every_axiom()) == set(schema.every_axiom()), name
        assert again.type_names() == schema.type_names()


def test_a_class_that_narrows_an_inherited_fields_datatype_keeps_it() -> None:
    """A field redeclared with another datatype is another property under the same name.

    Local field IRIs were keyed by name alone, so the child's `date` and the parent's
    `string` were one property with two datatypes and the loader kept either. The nearest
    declaration wins, as it always did in a pack, and the parent's other fields stay.
    """
    schema = load_text("""
types:
  - name: Attribute
    fields: [value, note]
  - name: Period
    parent: Attribute
    fields:
      - name: value
        datatype: date
""")

    declared = {one.name: one.datatype for one in schema.declared_fields("Period")}
    assert declared == {"value": "date", "note": "string"}
    assert {one.name: one.datatype for one in schema.declared_fields("Attribute")} == {
        "value": "string", "note": "string"}
    again = load_text(to_turtle(schema))
    assert {one.name: one.datatype for one in again.declared_fields("Period")} == declared


def test_a_term_named_with_a_space_and_no_iri_is_written_and_read_back_by_its_name() -> None:
    schema = load_text("""
types:
  - name: Measuring device
    fields: [serial number]
    description: A class with a space in its name and no identity of its own.
predicates:
  - name: calibrated against
    domain: Measuring device
    range: Measuring device
    description: A relation with a space in its name.
""")

    again = load_text(to_turtle(schema))

    assert [one.name for one in again.types] == ["Measuring device"]
    assert [one.name for one in again.predicates] == ["calibrated against"]
    assert [one.name for one in again.declared_fields("Measuring device")] == ["serial number"]
