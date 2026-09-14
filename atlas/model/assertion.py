"""Who asserted what, and the projection that turns a history into a graph.

A node or a link is never edited in place: a new assertion is recorded, naming the
one it supersedes. `current` is the reader of that history -- the latest assertion
per target that nothing supersedes -- and it is what makes the store a memory
rather than a dump, because a re-extraction lands under the human judgement already
recorded instead of overwriting it.

`at` is passed in and never read from the clock, so a run is reproducible and a
backfill can state the time it means rather than the time it ran. Assertions are
ordered by comparing that string, which holds as long as one store writes one
ISO-8601 form, and breaks the moment two writers mix offsets.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field

from atlas.model.base import Frozen
from atlas.model.graph import Link, Node

AgentKind = Literal["human", "model", "run"]
"""What an assertion may be attributed to. Named, because a step whose configuration
chooses one has to refuse the other spellings with the same three words in hand."""


class Agent(Frozen):
    """Whoever an assertion is attributed to: a person, a model, or one run of one."""

    id: str
    kind: AgentKind
    label: str = ""


class Assertion(Frozen):
    """One act of asserting: an agent, a time, a target, and what it replaces.

    The target is carried whole rather than referenced, so the assertion log is
    self-contained: replaying it reconstructs every state the graph has been in.
    """

    id: str
    agent: Agent
    at: str = Field(description="ISO-8601 timestamp, supplied by the caller")
    target: Node | Link
    supersedes: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def current(assertions: Iterable[Assertion]) -> tuple[Node | Link, ...]:
    """The state a body of assertions projects to: latest live assertion per target id.

    An assertion is dead once another one supersedes it, whatever its time; among
    what is left, the latest `at` wins, and a tie goes to the later assertion in the
    given order. Targets come back in the order their ids were first asserted.
    """
    log = list(assertions)
    superseded = {a.supersedes for a in log}
    latest: dict[str, Assertion] = {}
    for assertion in log:
        if assertion.id in superseded:
            continue
        kept = latest.get(assertion.target.id)
        if kept is None or assertion.at >= kept.at:
            latest[assertion.target.id] = assertion
    return tuple(assertion.target for assertion in latest.values())
