from __future__ import annotations

from pathlib import Path

import pytest

from atlas.contracts import Card, Edge, Span
from atlas.ontology import CORE_PATH, load, validate_card, validate_edge

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


def span(text: str = "a verbatim fragment") -> Span:
    return Span(doc_id="doc-1", page=1, start=0, end=len(text), text=text)


def card(type_name: str, fields: dict[str, str], spans: tuple[Span, ...] = ()) -> Card:
    return Card(
        id="card-1",
        type=type_name,
        fields=fields,
        spans=spans or (span(),),
        run_id="run-1",
        ontology_version="0" * 12,
    )


def edge(predicate: str) -> Edge:
    return Edge(
        src="card-1",
        predicate=predicate,
        dst="card-2",
        span=span(),
        run_id="run-1",
        ontology_version="0" * 12,
    )


def test_core_declares_six_types_and_eight_predicates() -> None:
    ontology = load()
    assert ontology.type_names() == {"Task", "Method", "Dataset", "Metric", "Result", "Claim"}
    assert len(ontology.predicates) == 8
    assert ontology.find_predicate("evaluated_on") is not None


def test_version_is_stable_across_loads_and_moves_with_the_extension(tmp_path: Path) -> None:
    assert load().version == load(CORE_PATH).version
    extended = load(extension_path=write(tmp_path, EXTENSION))
    assert extended.version != load().version
    assert len(extended.version) == 12
    assay = extended.find_type("Assay")
    assert assay is not None and assay.parent == "Method"


def test_extension_type_without_a_parent_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, "types:\n  - name: Assay\n    fields: [protocol]\n")
    with pytest.raises(ValueError, match="Assay"):
        load(extension_path=path)


def test_extension_type_with_an_unknown_parent_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, "types:\n  - name: Assay\n    parent: Instrument\n")
    with pytest.raises(ValueError, match="Instrument"):
        load(extension_path=path)


def test_duplicate_names_are_rejected(tmp_path: Path) -> None:
    types = write(tmp_path, "types:\n  - name: Method\n    parent: Task\n", "dup_type.yaml")
    with pytest.raises(ValueError, match="Method"):
        load(extension_path=types)
    predicates = write(
        tmp_path,
        "predicates:\n  - name: supports\n    domain: Task\n    range: Claim\n",
        "dup_predicate.yaml",
    )
    with pytest.raises(ValueError, match="supports"):
        load(extension_path=predicates)


def test_a_valid_card_passes_clean() -> None:
    method = card("Method", {"name": "a method", "summary": "what it does"})
    assert validate_card(method, load()) == []


def test_an_unknown_field_is_reported() -> None:
    violations = validate_card(card("Method", {"name": "a method", "accuracy": "0.9"}), load())
    assert len(violations) == 1
    assert "accuracy" in violations[0]


def test_an_unknown_type_is_reported() -> None:
    violations = validate_card(card("Instrument", {}), load())
    assert len(violations) == 1
    assert "Instrument" in violations[0]


def test_a_blank_span_is_reported() -> None:
    violations = validate_card(card("Task", {}, spans=(span("   "),)), load())
    assert violations != []


def test_an_extension_type_inherits_the_fields_of_its_parent(tmp_path: Path) -> None:
    ontology = load(extension_path=write(tmp_path, EXTENSION))
    assay = card("Assay", {"name": "an assay", "protocol": "step one"})
    assert validate_card(assay, ontology) == []


def test_edges_are_checked_against_domain_and_range() -> None:
    ontology = load()
    assert validate_edge(edge("addresses"), ontology, "Method", "Task") == []
    assert validate_edge(edge("nowhere"), ontology, "Method", "Task") != []
    swapped = validate_edge(edge("addresses"), ontology, "Task", "Method")
    assert len(swapped) == 2


def test_an_extension_type_satisfies_the_domain_of_its_parent(tmp_path: Path) -> None:
    ontology = load(extension_path=write(tmp_path, EXTENSION))
    assert validate_edge(edge("addresses"), ontology, "Assay", "Task") == []
    assert validate_edge(edge("calibrated_with"), ontology, "Assay", "Dataset") == []
