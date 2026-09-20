"""Tests for the map layer, and for the two-level search that must not confuse it with a class.

The claim the module makes is a separation: a topic groups things the corpus discusses
together and says nothing about what any of them is. `mixed` is where that is enforced,
and the test for it is the negative one -- a dense group of several kinds stays a
subject area. The search is tested for the property that makes the branch worth having
and for the one that makes it dangerous: it reaches nodes the question shares no word
with, and every hit says which branch reached it.
"""

from __future__ import annotations

from atlas.steps.index_nodes import Index
from atlas.steps.topics import RetrieveDualOptions, Topic, TopicsOptions, retrieve_dual, topics
from conftest import Fixture

DEFAULTS = TopicsOptions()


def built(science: Fixture, options: TopicsOptions = DEFAULTS) -> tuple[Topic, ...]:
    return topics({"store": science.store, "schema": science.schema}, options)["topics"]


def test_a_topic_is_a_connected_group_of_what_is_actually_related(science: Fixture) -> None:
    [topic] = built(science)

    # Every node of the fixture hangs together through the argument, so there is one
    # topic and it holds all of them.
    assert len(topic) == len(science.nodes)
    assert topic.terms


def test_a_group_of_several_kinds_is_a_subject_area_and_says_so(science: Fixture) -> None:
    [topic] = built(science)

    assert topic.mixed
    assert "Proposition" in topic.kinds and "StudyResult" in topic.kinds


def test_a_group_of_one_kind_is_not_mixed(science: Fixture) -> None:
    [topic] = topics(
        {"store": science.store, "schema": science.schema},
        TopicsOptions(follow=("comparable_with",)),
    )["topics"]

    # The two sets of conditions were checked against each other, so they hang together
    # and they are both conditions: a group of one kind, and not a mixed one.
    assert topic.kinds == ("Context",)
    assert not topic.mixed


def test_a_topic_too_small_to_be_one_is_left_out(science: Fixture) -> None:
    found = topics({"store": science.store, "schema": science.schema},
                   TopicsOptions(follow=("used_dataset",), min_size=3))["topics"]

    assert found == ()


def test_the_number_of_mixed_topics_is_reported(science: Fixture) -> None:
    result = topics({"store": science.store, "schema": science.schema}, DEFAULTS)

    assert result["mixed_topics"] == 1


def test_topics_are_rebuilt_and_never_asserted(science: Fixture) -> None:
    before = len(science.store.assertions())

    built(science)

    assert len(science.store.assertions()) == before


def test_the_question_branch_and_the_topic_branch_are_told_apart(science: Fixture) -> None:
    found = built(science)
    index = Index.of(science.store.nodes())

    result = retrieve_dual(
        {"store": science.store, "index": index, "topics": found, "question": "yield"},
        RetrieveDualOptions(limit=20),
    )

    ways = {hit.via for hit in result["hits"]}
    assert "question" in ways
    assert ways <= {"question", "topic"}


def test_the_topic_branch_reaches_a_node_the_question_shares_no_word_with(
    science: Fixture,
) -> None:
    found = built(science)
    index = Index.of(science.store.nodes())
    question = found[0].terms[0]

    through = retrieve_dual(
        {"store": science.store, "index": index, "topics": found, "question": question},
        RetrieveDualOptions(limit=50),
    )["hits"]
    without = retrieve_dual(
        {"store": science.store, "index": index, "topics": (), "question": question},
        RetrieveDualOptions(limit=50),
    )["hits"]

    assert len(through) > len(without)
    assert any(hit.via == "topic" for hit in through)


def test_a_node_reached_only_through_a_topic_scores_below_one_the_question_named(
    science: Fixture,
) -> None:
    found = built(science)
    index = Index.of(science.store.nodes())

    hits = retrieve_dual(
        {"store": science.store, "index": index, "topics": found, "question": "yield"},
        RetrieveDualOptions(limit=50, weight=0.1),
    )["hits"]

    named = [hit for hit in hits if hit.via == "question"]
    through = [hit for hit in hits if hit.via == "topic"]
    assert named and through
    assert min(hit.score for hit in named) >= max(hit.score for hit in through)


def test_turning_the_topic_branch_off_leaves_the_ordinary_ranking(science: Fixture) -> None:
    found = built(science)
    index = Index.of(science.store.nodes())

    hits = retrieve_dual(
        {"store": science.store, "index": index, "topics": found, "question": "yield"},
        RetrieveDualOptions(topics=0),
    )["hits"]

    assert all(hit.via == "question" for hit in hits)
