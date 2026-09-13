"""Loading tests: what a pack becomes, how packs merge, and what a bad pack raises.

Every type here comes from a file the test names. The core ships none, so `load()`
with no pack is the empty schema; the six machine-learning types live in
`packs/ml_paper.yaml` like any other domain's and are loaded explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.model import Node, Span
from atlas.ontology import load

PACK = Path(__file__).parents[1] / "packs" / "ml_paper.yaml"
NAMESPACE = "https://example.org/ontology/ml-paper#"

EXTENSION = """
types:
  - name: Assay
    parent: Method
    fields: [protocol]
predicates:
  - name: calibrated_with
    domain: Assay
    range: Dataset
"""


def write(tmp_path: Path, body: str, name: str = "extension.yaml") -> Path:
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
    schema = load(PACK)
    assert schema.type_names() == {"Task", "Method", "Dataset", "Metric", "Result", "Claim"}
    assert len(schema.predicates) == 8
    assert schema.find_predicate("evaluated_on") is not None
    assert schema.version != load().version


def test_curies_are_expanded_against_the_prefixes_of_their_own_pack() -> None:
    schema = load(PACK)
    task = schema.find_type("Task")
    assert task is not None and task.iri == f"{NAMESPACE}Task"
    assert schema.find_type(f"{NAMESPACE}Task") is task
    assert schema.find_type("ml:Task") is task
    assert schema.find_type("Dataset").mappings == ("schema:Dataset", "dcat:Dataset")


def test_the_version_is_the_hash_of_the_bytes_loaded(tmp_path: Path) -> None:
    extension = write(tmp_path, EXTENSION)
    assert load(PACK).version == load(PACK).version
    assert load(PACK, extension).version != load(PACK).version
    assert load(PACK, extension).version != load(extension, PACK).version
    assert len(load(PACK, extension).version) == 12


def test_packs_merge_and_a_child_inherits_across_the_seam(tmp_path: Path) -> None:
    schema = load(PACK, write(tmp_path, EXTENSION))
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
        load(PACK, path)


def test_a_parent_may_be_declared_after_its_child(tmp_path: Path) -> None:
    body = "types:\n  - name: Assay\n    parent: Instrument\n  - name: Instrument\n"
    assert load(write(tmp_path, body)).is_a("Assay", "Instrument")


def test_a_duplicate_name_is_rejected(tmp_path: Path) -> None:
    types = write(tmp_path, "types:\n  - name: Method\n", "dup_type.yaml")
    with pytest.raises(ValueError, match="Method"):
        load(PACK, types)
    predicates = write(
        tmp_path,
        "predicates:\n  - name: supports\n    domain: Task\n    range: Claim\n",
        "dup_predicate.yaml",
    )
    with pytest.raises(ValueError, match="supports"):
        load(PACK, predicates)


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
