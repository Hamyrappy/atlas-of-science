"""What one pass cost, and how much of what it claimed survived being checked.

A run is a record, not a process: nothing here starts, tracks or finishes anything,
and no step has to be written around it. It exists because the only honest quality
number a pass has -- how much of what the model offered was placed in the text and
kept -- is computed while the run is alive and then dies with it, leaving a store
that says what is there and never what it took or what was refused.

The counts are whatever the configuration counted, so this file, like the rest of the
metamodel, names no step, no key and no domain.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field

from atlas.model.base import Frozen


class Run(Frozen):
    """One pass over some inputs: when it ran, under what, what it cost, what it kept."""

    id: str
    at: str = Field(description="ISO-8601 timestamp, supplied by the caller")
    pipeline: str = Field(default="", description="The configuration that was run")
    schema_version: str = Field(default="", description="The vocabulary it wrote under")
    agent: str = Field(default="", description="Id of the agent its assertions are attributed to")
    counts: Mapping[str, int] = Field(
        default_factory=dict, description="Claimed, kept and refused, named by the configuration"
    )
    seconds: float = 0.0
    notes: str = ""
