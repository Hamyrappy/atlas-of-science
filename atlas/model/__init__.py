"""The metamodel: six concepts, and no vocabulary of any domain.

A source was read; a span is a verbatim region of it; a node is a typed thing and a
link a typed relation, both valid only under the schema they name; an assertion
records who claimed one of those, when, and what it replaces; a schema is the
ontology plugged in underneath, which this package never names and never loads.

Nodes and links are views: the state of the graph is the projection `current` makes
over a body of assertions. Everything a stage may rely on in another stage is here,
so this is also the one place where a rename breaks unrelated code.
"""

from __future__ import annotations

from atlas.model.assertion import Agent, AgentKind, Assertion, current
from atlas.model.base import SCHEMA_VERSION, Frozen
from atlas.model.graph import Evidenced, Link, Node
from atlas.model.owl import Axiom
from atlas.model.run import Run
from atlas.model.schema import FieldDef, PredicateDef, Schema, TypeDef
from atlas.model.source import Segment, Source, Span

__all__ = [
    "SCHEMA_VERSION",
    "Agent",
    "AgentKind",
    "Assertion",
    "Axiom",
    "Evidenced",
    "FieldDef",
    "Frozen",
    "Link",
    "Node",
    "PredicateDef",
    "Run",
    "Schema",
    "Segment",
    "Source",
    "Span",
    "TypeDef",
    "current",
]
