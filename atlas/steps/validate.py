"""Dropping the nodes the loaded schema refuses, and keeping what it said about them.

Validation is a step of its own rather than a constructor's business: a run scores the
markup it got, so an unknown type or an undeclared field costs one node and leaves the
rest of the pass standing. The violations travel on in the state, because a count with
no cases behind it says nothing about what went wrong.

What is kept and what is dropped is the loaded pack's ruling, so there is nothing for
a configuration to write under this name. It declares `options=Nothing`, and a file
writing one anyway -- a `strict` that was never read -- is refused while it is read
instead of running under a setting this step does not have.
"""

from __future__ import annotations

from atlas.model import Node, Schema
from atlas.steps import Nothing, State, register


@register("validate", requires=("nodes", "schema"), produces=("nodes", "violations"),
          options=Nothing)
def validate(state: State) -> State:
    """Keep the nodes the schema accepts, and report everything it said about the rest."""
    schema: Schema = state["schema"]
    kept: list[Node] = []
    violations: list[str] = []
    for node in state["nodes"]:
        problems = schema.validate_node(node)
        if problems:
            violations += problems
        else:
            kept.append(node)
    return {"nodes": tuple(kept), "violations": tuple(violations)}
