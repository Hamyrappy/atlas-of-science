"""Loading, merging and validation of the ontology.

The ontology is data: a frozen core file plus an optional domain extension,
hashed together into the version that every card carries. Validation returns a
list of violations instead of raising, because a run scores the markup it got
rather than aborting on the first bad card; only a broken ontology file raises.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

import yaml

from atlas.contracts import Card, Edge, Ontology, PredicateDef, TypeDef

CORE_PATH = Path(__file__).parent / "core.yaml"


def load(core_path: Path | None = None, extension_path: Path | None = None) -> Ontology:
    """Read the core and an optional extension, merge them, hash the raw bytes."""
    core_file = CORE_PATH if core_path is None else core_path
    raw = core_file.read_bytes()
    types, predicates = _parse(raw, core_file)

    if extension_path is not None:
        extension_bytes = extension_path.read_bytes()
        extension_types, extension_predicates = _parse(extension_bytes, extension_path)
        _check_parents(types, extension_types)
        raw = raw + extension_bytes
        types = types + extension_types
        predicates = predicates + extension_predicates

    _reject_duplicates(t.name for t in types)
    _reject_duplicates(p.name for p in predicates)
    version = hashlib.sha256(raw).hexdigest()[:12]
    return Ontology(version=version, types=types, predicates=predicates)


def validate_card(card: Card, ontology: Ontology) -> list[str]:
    """List everything wrong with a card under this ontology; empty means valid."""
    violations: list[str] = []
    if ontology.find_type(card.type) is None:
        violations.append(f"card {card.id}: unknown type {card.type!r}")
    else:
        declared = declared_fields(card.type, ontology)
        for key in card.fields:
            if key not in declared:
                violations.append(
                    f"card {card.id}: field {key!r} is not declared on type {card.type!r}"
                )
    # Card and Span already guarantee at least one span and non-empty span text, so
    # the only provenance defect that can reach here is text that is all whitespace.
    for span in card.spans:
        if not span.text.strip():
            violations.append(f"card {card.id}: blank span at {span.doc_id} page {span.page}")
    return violations


def declared_fields(name: str, ontology: Ontology) -> tuple[str, ...]:
    """The fields a type declares, followed by the ones it inherits, without repeats."""
    fields: list[str] = []
    for type_def in _ancestry(name, ontology):
        fields.extend(field for field in type_def.fields if field not in fields)
    return tuple(fields)


def validate_edge(edge: Edge, ontology: Ontology, src_type: str, dst_type: str) -> list[str]:
    """List everything wrong with an edge, given the types of the cards it joins."""
    predicate = ontology.find_predicate(edge.predicate)
    if predicate is None:
        return [f"edge {edge.src}->{edge.dst}: unknown predicate {edge.predicate!r}"]
    violations: list[str] = []
    if not _is_a(src_type, predicate.domain, ontology):
        violations.append(
            f"edge {edge.src}->{edge.dst}: predicate {predicate.name!r} "
            f"expects domain {predicate.domain!r}, source is {src_type!r}"
        )
    if not _is_a(dst_type, predicate.range, ontology):
        violations.append(
            f"edge {edge.src}->{edge.dst}: predicate {predicate.name!r} "
            f"expects range {predicate.range!r}, target is {dst_type!r}"
        )
    return violations


def _parse(raw: bytes, path: Path) -> tuple[tuple[TypeDef, ...], tuple[PredicateDef, ...]]:
    document = yaml.safe_load(raw) or {}
    if not isinstance(document, dict):
        raise ValueError(f"{path}: ontology file must be a mapping")
    types = tuple(TypeDef(**entry) for entry in document.get("types") or ())
    predicates = tuple(PredicateDef(**entry) for entry in document.get("predicates") or ())
    return types, predicates


def _check_parents(core: tuple[TypeDef, ...], extension: tuple[TypeDef, ...]) -> None:
    # A parent must already be known when its child is read. That forbids forward
    # references, and with them cycles, so the ancestor walks below terminate.
    known = {t.name for t in core}
    for type_def in extension:
        if type_def.parent is None:
            raise ValueError(f"extension type {type_def.name!r} must declare a parent")
        if type_def.parent not in known:
            raise ValueError(
                f"extension type {type_def.name!r} has unknown parent {type_def.parent!r}"
            )
        known.add(type_def.name)


def _reject_duplicates(names: Iterable[str]) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"duplicate ontology name {name!r}")
        seen.add(name)


def _ancestry(name: str, ontology: Ontology) -> list[TypeDef]:
    chain: list[TypeDef] = []
    seen: set[str] = set()
    current = ontology.find_type(name)
    # A hand-edited core file may declare a parent cycle, which nothing above checks.
    while current is not None and current.name not in seen:
        seen.add(current.name)
        chain.append(current)
        current = ontology.find_type(current.parent) if current.parent else None
    return chain


def _is_a(name: str, expected: str, ontology: Ontology) -> bool:
    return any(t.name == expected for t in _ancestry(name, ontology))
