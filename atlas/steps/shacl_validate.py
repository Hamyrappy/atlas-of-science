"""Validating the run's record against SHACL shapes, in closed world, before it is written.

`validate` checks each node against its class's declared fields, one at a time. This checks
the record as a graph: the nodes and the links together, against the shapes the ontology
implies -- each class closed over its own fields, every node on a span, every relation's
domain and range as a closed-world class check -- and the shapes the configuration named
(`schema: {shapes: [...]}`), which state what OWL cannot: a computation that depends on
itself through a chain, a statement on two propositions, a result with no conditions.

**A violation refuses the object; a warning keeps it.** A refused node is removed from
`nodes`, and so is every link touching it, since a relation to something that was not
written is a relation to nothing. A refused link is removed on its own -- and a domain or
range check refuses the relation, not the node at its end, since the node may be exactly
what it says it is and the relation the thing that was misread. Both are reported
in `shacl_violations` with the shape's own message, so a run that refused a third of its
record says why in words, and a warning is kept beside the object it is about.

It runs where `validate` runs, after the relations are located and before anything is
asserted, so what it refuses never reaches the store. A relation that reaches a node already
in the store is checked against that node as stored -- it is read in as context, so a range
check sees its class -- and nothing already stored is ever refused here: what a store holds
is superseded, not rejected after the fact.
"""

from __future__ import annotations

from pydantic import Field

from atlas.model import Frozen, Link, Node, Schema
from atlas.reason.shacl import Violation, validate
from atlas.steps import State, register


class ShaclOptions(Frozen):
    """Whether the ontology's own shapes are generated, and whether a violation refuses."""

    generate: bool = Field(True, description="Apply the shapes the ontology itself implies")
    refuse: bool = Field(True, description="Remove what a violation is found on")


@register("shacl_validate", requires=("nodes", "schema"),
          produces=("nodes", "links", "shacl_violations", "shacl_conforms"),
          options=ShaclOptions)
def shacl_validate(state: State, options: ShaclOptions) -> State:
    """Validate the record as a graph, and keep what passes."""
    schema: Schema = state["schema"]
    nodes: tuple[Node, ...] = tuple(state["nodes"])
    links: tuple[Link, ...] = tuple(state.get("links", ()))
    own = {node.id for node in nodes} | {link.id for link in links}
    ends = {end for link in links for end in (link.src, link.dst)} - own
    store = state.get("store")
    context = tuple(store.get_nodes(sorted(ends))) if store is not None and ends else ()
    report = validate(schema, (*nodes, *context), links, generate=options.generate)
    # Only this run's record is judged; a stored node read in as context is not.
    found = tuple(one for one in report.violations if one.target is None or one.target in own)
    refused = {one.target for one in found if one.refuses and one.target}
    if not options.refuse:
        refused = set()
    kept_nodes = tuple(node for node in nodes if node.id not in refused)
    kept_links = tuple(
        link for link in links
        if not {link.id, link.src, link.dst} & refused
    )
    return {"nodes": kept_nodes, "links": kept_links, "shacl_violations": found,
            "shacl_conforms": not any(one.refuses for one in found)}


def refused_by(violations: tuple[Violation, ...]) -> dict[str, list[str]]:
    """What each refused object was refused for, in the shapes' own words."""
    found: dict[str, list[str]] = {}
    for one in violations:
        if one.refuses and one.target:
            found.setdefault(one.target, []).append(one.message)
    return found


__all__ = ["ShaclOptions", "refused_by", "shacl_validate"]
