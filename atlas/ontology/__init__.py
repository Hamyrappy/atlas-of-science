"""Reading ontology packs off disk and merging them into one `Schema`.

The core ships no vocabulary: `load()` with nothing to load is an empty schema, and
every type a corpus uses arrives from a pack under `packs/`. This module is the only
one that touches the filesystem; what the terms mean, and whether an object satisfies
them, is `atlas.model.schema` and is not repeated here.

The version is the hash of the bytes read, in the order they were given, so an object
records the exact vocabulary it was written under and an edit to any pack moves it.
A pack that declares prefixes is claiming identities, so each of its terms must carry
an IRI, written out or as a CURIE that is expanded against that pack's own prefixes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

import yaml

from atlas.model import FieldDef, PredicateDef, Schema, TypeDef


def load(*paths: Path | str) -> Schema:
    """Merge the packs at these paths, in order, into one versioned schema."""
    raw = b""
    prefixes: dict[str, str] = {}
    types: list[TypeDef] = []
    predicates: list[PredicateDef] = []
    for path in map(Path, paths):
        body = path.read_bytes()
        raw += body
        pack = _parse(body, path)
        prefixes |= pack.prefixes
        types += pack.types
        predicates += pack.predicates
    _reject_duplicates(t.name for t in types)
    _reject_duplicates(p.name for p in predicates)
    schema = Schema(
        version=hashlib.sha256(raw).hexdigest()[:12],
        prefixes=prefixes,
        types=tuple(types),
        predicates=tuple(predicates),
    )
    _check_parents(schema)
    return schema


def _parse(raw: bytes, path: Path) -> Schema:
    document = yaml.safe_load(raw) or {}
    if not isinstance(document, dict):
        raise ValueError(f"{path}: a pack must be a mapping")
    # An unversioned schema over the pack's own prefixes: it is what knows how a CURIE
    # expands, so the terms below are resolved against their own file, not the merge.
    scope = Schema(version="", prefixes=document.get("prefixes") or {})
    return scope.model_copy(
        update={
            "types": tuple(_type(entry, scope, path) for entry in document.get("types") or ()),
            "predicates": tuple(
                PredicateDef(**{**entry, "iri": _iri(entry, scope, path)})
                for entry in document.get("predicates") or ()
            ),
        }
    )


def _type(entry: dict, scope: Schema, path: Path) -> TypeDef:
    fields = tuple(_field(field, scope) for field in entry.get("fields") or ())
    return TypeDef(**{**entry, "iri": _iri(entry, scope, path), "fields": fields})


def _field(entry: dict | str, scope: Schema) -> FieldDef:
    """A field is a mapping, or bare name shorthand for one that declares nothing else."""
    entry = {"name": entry} if isinstance(entry, str) else entry
    iri = entry.get("iri")
    return FieldDef(**{**entry, "iri": scope.expand(iri) if iri else None})


def _iri(entry: dict, scope: Schema, path: Path) -> str | None:
    iri = entry.get("iri")
    if iri is None and scope.prefixes:
        raise ValueError(f"{path}: term {entry.get('name')!r} declares no iri")
    return scope.expand(iri) if iri else None


def _check_parents(schema: Schema) -> None:
    for type_def in schema.types:
        if type_def.parent is not None and schema.find_type(type_def.parent) is None:
            raise ValueError(f"type {type_def.name!r} has unknown parent {type_def.parent!r}")


def _reject_duplicates(names: Iterable[str]) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"duplicate name {name!r}")
        seen.add(name)
