"""Checking the ontology before a run is written under it, and never checking the data.

A pack is a set of axioms and it can be wrong in ways that no amount of good extraction
will survive: a type disjoint from its own ancestor, a relation whose inverse points
somewhere else, a transitive relation between two types nothing can be both of. Every
node written under such a pack is written under a contradiction, and finding out later
means re-extracting a corpus.

So the ontology is checked at release, which is the one place this library runs anything
resembling a reasoner, and a run whose pack does not pass does not start. The rule from
CLAUDE.md is kept exactly: **the check runs over the schema and never over extracted
data.** Open-world inference over markup would invent the missing spans the markup layer
exists to refuse, so nothing here reads a node.

Two decisions are worth their own paragraph.

**An unsatisfiable type fails the release even though nothing instantiates it.** A pack
whose `Reagent` is a subclass of `MaterialEntity` and also disjoint from it is consistent
in the trivial sense -- no instance, no contradiction -- and it is broken, because the
first extractor that produces a `Reagent` produces a node that cannot exist. Consistency
of the whole is not the property worth checking; satisfiability of each class is.

**A check that was not run is reported as not run.** Where a budget stops the checking,
`unchecked` names what was skipped and `passed` is false. "Nothing was found" and
"nothing was looked for" are different answers, and a gate that conflated them would
pass every pack too large to check.

The gate has two layers. The syntactic one below -- parents, cycles, disjointness in a
class's own ancestry, domains, ranges, characteristics, inverses -- runs on every
ontology, and names what is wrong in words a person editing a file can act on. Behind it
runs an engine: the OWL 2 EL classifier, or, with `engine: dl`, the tableau
(`atlas/reason/tableau.py`), which decides the consistency of the whole ontology and the
satisfiability of every class over *all* of its axioms -- unions, cardinalities, inverses
and chains included. The EL engine finds every empty class an EL ontology has and some an
expressive one has; the tableau finds them all, and says so. And where a configuration
names a profile, the gate reports every axiom outside it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Schema
from atlas.model.owl import TOP
from atlas.model.schema import CHARACTERISTICS
from atlas.reason.el import classify
from atlas.reason.profile import outside, profiles
from atlas.reason.tableau import decide
from atlas.steps import State, register

Kind = Literal[
    "cycle", "unsatisfiable", "unknown-parent", "unknown-domain", "unknown-range",
    "unknown-disjoint", "inverse-mismatch", "unknown-inverse", "unknown-characteristic",
    "self-disjoint", "inconsistent", "outside-profile",
]
"""Everything a pack can be wrong about that is visible without looking at any data."""

CHECKS = ("hierarchy", "disjointness", "relations", "inverses", "engine", "profile")
"""The groups of checks, named so that a budget can say which of them it skipped: four
over the vocabulary, one by the engine over every axiom, one against the profile."""

Engine = Literal["el", "dl"]


class Problem(Frozen):
    """One thing wrong with a pack, named by kind, term and what exactly is wrong."""

    kind: Kind
    term: str
    detail: str


class Report(Frozen):
    """What the gate found, what it checked, and therefore whether a release may proceed."""

    problems: tuple[Problem, ...] = ()
    checked: tuple[str, ...] = ()
    unchecked: tuple[str, ...] = ()
    profiles: tuple[str, ...] = Field(
        default=(), description="Every OWL 2 profile the ontology is entirely within"
    )
    engine: str = ""

    @property
    def passed(self) -> bool:
        """A release passes when nothing was found **and** everything was looked for."""
        return not self.problems and not self.unchecked

    def __len__(self) -> int:
        return len(self.problems)


class FormalCheckOptions(Frozen):
    """How much may be checked, and whether a failing pack stops the run.

    `budget` is in types: a pack larger than it leaves the checks that walk the whole
    hierarchy unrun, and the report says so rather than passing. `strict` is what makes
    this a gate rather than an audit -- with it on, a pack that does not pass raises
    before anything is written under it.
    """

    budget: int = Field(2000, gt=0)
    strict: bool = True
    engine: Engine = Field(
        default="el",
        description="`el` classifies completely in polynomial time and finds every empty "
                    "class of an EL ontology; `dl` runs the tableau over every axiom",
    )


@register("formal_check", requires=("schema",), produces=("formal", "problems"),
          options=FormalCheckOptions)
def formal_check(state: State, options: FormalCheckOptions) -> State:
    """Check the loaded pack, and refuse the run if it does not pass and `strict` is set."""
    report = inspect(state["schema"], budget=options.budget, engine=options.engine)
    if options.strict and not report.passed:
        raise ValueError(
            "the pack does not pass the formal gate: "
            + "; ".join(f"{one.kind} on {one.term!r}: {one.detail}" for one in report.problems[:5])
            + (f"; and {len(report.problems) - 5} more" if len(report.problems) > 5 else "")
            + (f"; unchecked: {', '.join(report.unchecked)}" if report.unchecked else "")
        )
    return {"formal": report, "problems": report.problems}


def inspect(schema: Schema, budget: int = 2000, engine: Engine = "el") -> Report:
    """Everything wrong with an ontology, by group, with what was skipped for budget."""
    if len(schema.types) > budget:
        # Nothing was looked for, so nothing may be concluded. Naming the groups that
        # were skipped is the difference between an honest gate and a rubber stamp.
        return Report(unchecked=CHECKS)
    problems = [
        *_hierarchy(schema),
        *_disjointness(schema),
        *_relations(schema),
        *_inverses(schema),
    ]
    engine_problems, skipped = _engine(schema, engine)
    named = {(one.kind, one.term) for one in problems}
    problems += [one for one in engine_problems if (one.kind, one.term) not in named]
    axioms = schema.every_axiom()
    if schema.profile:
        problems += [
            Problem(kind="outside-profile", term=schema.profile,
                    detail=f"{axiom.text()} is not OWL 2 {schema.profile}")
            for axiom in outside(axioms, schema.profile)
        ]
    checked = tuple(one for one in CHECKS if one not in skipped)
    return Report(problems=tuple(problems), checked=checked, unchecked=tuple(skipped),
                  profiles=profiles(axioms), engine=engine)


def _engine(schema: Schema, engine: Engine) -> tuple[list[Problem], tuple[str, ...]]:
    """What the engine finds over every axiom: an inconsistent ontology, and empty classes.

    The EL engine reads the EL part of the ontology, so what it finds is true and what it
    misses is what the rest would have shown; the tableau reads all of it, and a question
    it could not settle within its budget, or an axiom it does not decide, leaves the
    engine group unchecked -- which fails the gate rather than passing it.
    """
    names = [one.name for one in schema.types]
    if engine == "el":
        found = classify(schema.every_axiom(), names)
        return ([Problem(kind="unsatisfiable", term=name,
                         detail="the EL engine derives that nothing can be one")
                 for name in sorted(found.unsatisfiable)], ())
    verdict = decide(schema.every_axiom(), names)
    problems: list[Problem] = []
    if verdict.consistent is False:
        problems.append(Problem(kind="inconsistent", term=schema.iri or "the ontology",
                                detail="the tableau finds that no model satisfies every axiom"))
    problems += [Problem(kind="unsatisfiable", term=name,
                         detail="the tableau finds that nothing can be one")
                 for name in verdict.unsatisfiable]
    skipped = ("engine",) if not verdict.decided else ()
    return problems, skipped


def _hierarchy(schema: Schema) -> list[Problem]:
    """Parents that do not exist, and cycles, which would make ancestry meaningless."""
    found: list[Problem] = []
    for type_def in schema.types:
        if type_def.parent and schema.find_type(type_def.parent) is None:
            found.append(Problem(kind="unknown-parent", term=type_def.name,
                                 detail=f"parent {type_def.parent!r} is not a type of this pack"))
            continue
        seen: set[str] = set()
        current = type_def
        while current is not None and current.name not in seen:
            seen.add(current.name)
            current = schema.find_type(current.parent) if current.parent else None
        if current is not None:
            found.append(Problem(kind="cycle", term=type_def.name,
                                 detail=f"its ancestry returns to {current.name!r}"))
    return found


def _disjointness(schema: Schema) -> list[Problem]:
    """Types nothing can be, which is the check this module exists for.

    A class is unsatisfiable when its own ancestry contains two types the pack declares
    disjoint -- including the case where the type is declared disjoint from something it
    descends from. No instance is needed for that to be a defect: the first one produced
    would be a node that cannot exist.
    """
    found: list[Problem] = []
    for type_def in schema.types:
        for named in type_def.disjoint_with:
            if schema.find_type(named) is None:
                found.append(Problem(kind="unknown-disjoint", term=type_def.name,
                                     detail=f"disjoint from {named!r}, which is not a type here"))
            elif schema.is_a(type_def.name, named):
                found.append(Problem(
                    kind="self-disjoint", term=type_def.name,
                    detail=f"declared disjoint from {named!r}, which it descends from",
                ))
        ancestry = [one.name for one in schema.ancestry(type_def.name)]
        clashes = sorted({
            (here, there)
            for here in ancestry for there in ancestry
            if here < there and schema.disjoint(here, there)
        })
        found += [
            Problem(kind="unsatisfiable", term=type_def.name,
                    detail=f"it is both {here!r} and {there!r}, which the pack declares disjoint")
            for here, there in clashes
        ]
    return found


def _relations(schema: Schema) -> list[Problem]:
    """Domains and ranges that name nothing, and characteristics the library cannot execute."""
    found: list[Problem] = []
    for predicate in schema.predicates:
        # owl:Thing is a relation with no domain or range stated, which is not a mistake.
        if predicate.domain != TOP and schema.find_type(predicate.domain) is None:
            found.append(Problem(kind="unknown-domain", term=predicate.name,
                                 detail=f"domain {predicate.domain!r} is not a class here"))
        if predicate.range != TOP and schema.find_type(predicate.range) is None:
            found.append(Problem(kind="unknown-range", term=predicate.name,
                                 detail=f"range {predicate.range!r} is not a class here"))
        found += [
            Problem(kind="unknown-characteristic", term=predicate.name,
                    detail=f"{named!r} is not one this library executes: "
                           f"{', '.join(CHARACTERISTICS)}")
            for named in predicate.characteristics
            if named not in CHARACTERISTICS
        ]
        # A transitive relation composes with itself, so its range has to be something
        # its domain can be. Declared between two disjoint types, it can never compose.
        if "transitive" in predicate.characteristics and schema.disjoint(
            predicate.domain, predicate.range
        ):
            found.append(Problem(
                kind="unsatisfiable", term=predicate.name,
                detail=f"transitive between {predicate.domain!r} and {predicate.range!r}, "
                       "which are disjoint, so it can never compose",
            ))
    return found


def _inverses(schema: Schema) -> list[Problem]:
    """Inverse pairs that do not mirror, which would derive a relation nothing supports."""
    found: list[Problem] = []
    for predicate in schema.predicates:
        if not predicate.inverse_of:
            continue
        other = schema.find_predicate(predicate.inverse_of)
        if other is None:
            found.append(Problem(kind="unknown-inverse", term=predicate.name,
                                 detail=f"inverse of {predicate.inverse_of!r}, which is not "
                                        "a relation of this pack"))
            continue
        if not (schema.is_a(other.range, predicate.domain)
                and schema.is_a(other.domain, predicate.range)):
            found.append(Problem(
                kind="inverse-mismatch", term=predicate.name,
                detail=f"{predicate.domain}->{predicate.range} is not the mirror of "
                       f"{other.name}: {other.domain}->{other.range}",
            ))
    return found
