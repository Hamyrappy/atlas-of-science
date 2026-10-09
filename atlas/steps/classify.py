"""Classifying the ontology a run is under: which classes fall under which, and which are empty.

Loading already classifies with the EL engine, and `Schema.is_a` answers from that. This
step is for a configuration that wants the answer in its state -- to show it, to record it
beside a run, or to stop on it -- and for one whose ontology is more than EL, where the
complete answer needs the tableau.

With `engine: el` it re-runs the EL classifier and returns the hierarchy and the empty
classes, together with the axioms EL could not read: the answer is complete exactly when
that list is empty. With `engine: dl` it asks the tableau, over every axiom, whether each
named class can have a member, and -- where the ontology is small enough, since it is one
satisfiability test per pair -- whether each class is subsumed by each other one.

Nothing here reads a node. Classification is a question about the ontology, and a class
the axioms make empty is empty however many nodes were written under it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Schema
from atlas.model.owl import named
from atlas.reason.el import classify as el_classify
from atlas.reason.tableau import Budget, decide, nnf, prepare, satisfiable
from atlas.steps import State, register


class Classification(Frozen):
    """What an engine concluded about the named classes of an ontology."""

    engine: str
    hierarchy: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    unsatisfiable: tuple[str, ...] = ()
    complete: bool = True
    left_out: tuple[str, ...] = Field(
        default=(), description="Axioms the engine did not read, as functional syntax"
    )


class ClassifyOptions(Frozen):
    """Which engine, and how many classes the tableau may classify pairwise."""

    engine: Literal["el", "dl"] = "el"
    pairwise_limit: int = Field(
        60, ge=0, description="Above this many classes the tableau checks satisfiability only"
    )
    strict: bool = Field(False, description="Refuse the run if any class is empty")


@register("classify", requires=("schema",),
          produces=("classification", "hierarchy", "unsatisfiable"), options=ClassifyOptions)
def classify(state: State, options: ClassifyOptions) -> State:
    """Classify the ontology with the named engine, and stop if asked to and a class is empty."""
    schema: Schema = state["schema"]
    result = by_el(schema) if options.engine == "el" else by_dl(schema, options.pairwise_limit)
    if options.strict and result.unsatisfiable:
        raise ValueError(f"these classes can have no member: {', '.join(result.unsatisfiable)}")
    return {"classification": result, "hierarchy": result.hierarchy,
            "unsatisfiable": result.unsatisfiable}


def by_el(schema: Schema) -> Classification:
    found = el_classify(schema.every_axiom(), [one.name for one in schema.types])
    return Classification(engine="el", hierarchy=found.hierarchy(),
                          unsatisfiable=tuple(sorted(found.unsatisfiable)),
                          complete=found.complete,
                          left_out=tuple(one.text() for one in found.ignored))


def by_dl(schema: Schema, pairwise_limit: int) -> Classification:
    names = [one.name for one in schema.types]
    verdict = decide(schema.every_axiom(), names)
    hierarchy: dict[str, tuple[str, ...]] = {}
    complete = verdict.decided
    if len(names) <= pairwise_limit and verdict.consistent:
        prepared = prepare(schema.every_axiom())
        empty = set(verdict.unsatisfiable)
        for sub in names:
            if sub in empty:
                continue
            above = []
            for sup in names:
                if sup == sub:
                    continue
                difference = ("and", frozenset([nnf(named(sub)), nnf(named(sup), True)]))
                try:
                    if not satisfiable(difference, prepared):
                        above.append(sup)
                except Budget:
                    complete = False
            hierarchy[sub] = tuple(sorted(above))
    else:
        complete = False
        hierarchy = dict(schema.hierarchy)
    return Classification(engine="dl", hierarchy=hierarchy,
                          unsatisfiable=tuple(sorted(verdict.unsatisfiable)),
                          complete=complete,
                          left_out=tuple(one.text() for one in verdict.outside))


__all__ = ["Classification", "ClassifyOptions", "by_dl", "by_el", "classify"]
