"""The shape every object of the metamodel shares: a frozen, strictly typed value.

These objects are hashed and compared by content, so they must not be mutable and
must not silently absorb a key nobody declared; either would break the ids that
identify them. `SCHEMA_VERSION` versions these containers, not the ontology
plugged into them: that one is data and travels per object as `schema_version`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = 1


class Frozen(BaseModel):
    """Objects are values: immutable, compared by content, strict about types."""

    model_config = ConfigDict(frozen=True, extra="forbid")
