"""Tests for taking in what other registries published, and counting confirmations honestly.

Two claims, and both are ways a federation quietly becomes worthless. Nothing is taken
on trust: a record whose evidence no longer cuts its own text out of the source it cites
is held with the reason. And two publishers are not two confirmations when they read the
same paper, which is the error a federation exists to make and has to be built not to
make.
"""

from __future__ import annotations

from atlas.model import Agent, Assertion, Node, Segment, Source, Span
from atlas.steps.federate import (
    FederateOptions,
    check,
    count_independence,
    federate,
    independence,
)
from atlas.steps.graph_expand import Bundle
from atlas.store.memory import MemoryStore

TEXT = "The yield rose by four per cent in the second series of runs.\n"
VERSION = "0" * 12
AGENT = Agent(id="publisher", kind="run")


def source(source_id: str, text: str = TEXT) -> Source:
    return Source(id=source_id, origin=f"{source_id}.txt",
                  segments=(Segment(number=1, text=text),))


def node(node_id: str, held: Source, quote: str = "The yield rose", version: str = VERSION) -> Node:
    start = held.segment_text(1).index(quote)
    return Node(id=node_id, type="Thing", fields={"name": quote},
                spans=(Span.of(held, 1, start, start + len(quote)),), schema_version=version)


def registry(*pairs: tuple[Source, Node]) -> MemoryStore:
    store = MemoryStore()
    for index, (held, one) in enumerate(pairs):
        if store.get_source(held.id) is None:
            store.add_source(held)
        store.assert_(Assertion(id=f"{one.id}-{index}", agent=AGENT,
                                at="2026-01-01T00:00:00+00:00", target=one))
    return store


PAPER = source("paper-1")
OTHER = source("paper-2", "A second laboratory found no change at all in its runs.\n")
CLAIM = node("a" * 16, PAPER)
SECOND = node("b" * 16, OTHER, quote="no change at all")


def test_records_from_several_registries_land_in_one_snapshot() -> None:
    options = FederateOptions(registries={
        "one": registry((PAPER, CLAIM)),
        "two": registry((OTHER, SECOND)),
    })

    result = federate({}, options)

    assert result["synced"] == 2
    assert {one.id for one in result["store"].nodes()} == {CLAIM.id, SECOND.id}
    assert result["held"] == ()


def test_a_record_carries_the_registries_it_came_from() -> None:
    options = FederateOptions(registries={
        "one": registry((PAPER, CLAIM)),
        "two": registry((PAPER, CLAIM)),
    })

    result = federate({}, options)

    assert result["origins"][CLAIM.id] == ("one", "two")


class Publishing:
    """A registry that published its assertions and not the sources behind them."""

    def sources(self) -> tuple[Source, ...]:
        return ()

    def assertions(self, target_id: str | None = None) -> tuple[Assertion, ...]:
        return (Assertion(id="x", agent=AGENT, at="2026-01-01T00:00:00+00:00", target=CLAIM),)


def test_a_record_whose_source_was_not_published_is_held() -> None:
    result = federate({}, FederateOptions(registries={"one": Publishing()}))

    assert result["synced"] == 0
    assert "published no source" in result["held"][0].reason


def test_evidence_that_no_longer_cuts_its_own_text_is_held() -> None:
    drifted = source("paper-1", "Something else entirely was written here instead.\n")

    reason = check(
        Assertion(id="x", agent=AGENT, at="2026-01-01T00:00:00+00:00", target=CLAIM),
        {"paper-1": drifted},
        (),
    )

    assert "no longer cuts its own text" in reason


def test_a_record_under_an_unmapped_vocabulary_is_held_and_not_dropped() -> None:
    stranger = node("c" * 16, PAPER, version="ffffffffffff")

    result = federate(
        {},
        FederateOptions(registries={"one": registry((PAPER, stranger))}, versions=(VERSION,)),
    )

    assert result["synced"] == 0
    [held] = result["held"]
    assert "unmapped here" in held.reason
    # Held, so somebody can publish the mapping and sync again.
    assert held.target_id == stranger.id


def test_a_record_under_a_known_vocabulary_passes() -> None:
    result = federate(
        {},
        FederateOptions(registries={"one": registry((PAPER, CLAIM))}, versions=(VERSION,)),
    )

    assert result["synced"] == 1


def test_three_registries_reading_one_paper_are_one_confirmation() -> None:
    counted = independence(
        [CLAIM], {CLAIM.id: ("one", "two", "three")}
    )

    assert counted.independent == 1
    assert counted.registries == 3
    assert counted.republished == ("paper-1",)


def test_two_papers_are_two_confirmations() -> None:
    counted = independence(
        [CLAIM, SECOND], {CLAIM.id: ("one",), SECOND.id: ("two",)}
    )

    assert counted.independent == 2
    assert counted.republished == ()


def test_the_step_counts_over_the_package_it_is_given() -> None:
    bundle = Bundle(roots=(CLAIM.id,), nodes=(CLAIM,))

    result = count_independence({"bundle": bundle, "origins": {CLAIM.id: ("one", "two")}})

    assert result["independence"].independent == 1
    assert result["independence"].registries == 2
