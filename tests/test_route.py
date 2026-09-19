"""Tests for choosing which kind of question this is, and for seeding the walk by it.

Two claims. The router is deterministic first and says what decided it, and the markers
are the configuration's words -- with nothing named, everything goes to the default.
And an overview does not take a top-k: it takes whole communities, because a question
about how much of a field does something is a question about a set.
"""

from __future__ import annotations

from atlas.llm import Reply
from atlas.steps.communities import CommunitiesOptions, communities
from atlas.steps.index_nodes import Index
from atlas.steps.route import RetrieveRoutedOptions, RouteOptions, retrieve_routed, route
from conftest import Fixture

MARKED = RouteOptions(routes=("fact", "overview"),
                      markers={"overview": ("how has", "trend")}, default="fact")


class StubClient:
    def __init__(self, body: dict | None = None) -> None:
        self.body = body or {}
        self.calls = 0

    def complete(self, prompt: str, *, schema: dict | None = None,
                 system: str | None = None) -> Reply:
        raise AssertionError("the router asks for JSON, not prose")

    def complete_json(self, prompt: str, schema: dict, *,
                      system: str | None = None) -> tuple[dict, Reply]:
        self.calls += 1
        return self.body, Reply(text="", usage={}, cached=False)


def test_a_marker_chooses_the_route_and_is_named_as_the_reason() -> None:
    result = route({"question": "How has this field moved?"}, MARKED)

    assert result["route"] == "overview"
    assert "matched marker 'how has'" in result["route_reason"]


def test_nothing_matched_goes_to_the_default_and_says_so() -> None:
    result = route({"question": "What did paper A find?"}, MARKED)

    assert result["route"] == "fact"
    assert "the default route" in result["route_reason"]


def test_with_no_markers_configured_every_question_takes_the_default() -> None:
    result = route({"question": "How has this field moved?"}, RouteOptions())

    assert result["route"] == "fact"


def test_the_model_is_not_asked_unless_a_run_asks_for_it() -> None:
    client = StubClient({"route": "overview"})

    result = route({"question": "What did paper A find?", "client": client}, MARKED)

    assert client.calls == 0
    assert result["route"] == "fact"


def test_the_model_decides_only_where_nothing_matched() -> None:
    client = StubClient({"route": "overview"})
    asking = MARKED.model_copy(update={"ask_model": True})

    result = route({"question": "What did paper A find?", "client": client}, asking)

    assert client.calls == 1
    assert result["route"] == "overview"
    assert result["route_reason"] == "chosen by the model"


def test_a_marker_still_wins_over_the_model_and_costs_no_call() -> None:
    client = StubClient({"route": "fact"})
    asking = MARKED.model_copy(update={"ask_model": True})

    result = route({"question": "trend over five years", "client": client}, asking)

    assert client.calls == 0
    assert result["route"] == "overview"


def test_a_model_naming_a_route_that_is_not_on_offer_falls_through() -> None:
    client = StubClient({"route": "invented"})
    asking = MARKED.model_copy(update={"ask_model": True})

    result = route({"question": "What did paper A find?", "client": client}, asking)

    assert result["route"] == "fact"


def seeded(science: Fixture, which: str, options: RetrieveRoutedOptions) -> dict:
    index = Index.of(science.store.nodes())
    found = communities({"store": science.store, "schema": science.schema},
                        CommunitiesOptions(min_size=1))["communities"]
    return retrieve_routed(
        {"store": science.store, "index": index, "question": "yield",
         "route": which, "communities": found},
        options,
    )


def test_a_fact_route_takes_the_ranked_nodes(science: Fixture) -> None:
    result = seeded(science, "fact", RetrieveRoutedOptions(limit=2))

    assert len(result["hits"]) <= 2
    assert {hit.via for hit in result["hits"]} == {"fact"}
    assert not result["route_capped"]


def test_an_overview_route_takes_whole_communities_rather_than_a_top_k(
    science: Fixture,
) -> None:
    ranked = seeded(science, "fact", RetrieveRoutedOptions(limit=2))
    whole = seeded(science, "overview", RetrieveRoutedOptions(limit=2))

    assert len(whole["hits"]) > len(ranked["hits"])
    assert {hit.via for hit in whole["hits"]} == {"overview"}


def test_an_overview_that_could_not_take_the_whole_set_says_so(science: Fixture) -> None:
    result = seeded(science, "overview", RetrieveRoutedOptions(cap=2))

    assert len(result["hits"]) == 2
    assert result["route_capped"]


def test_an_overview_with_no_communities_falls_back_to_nothing_rather_than_guessing(
    science: Fixture,
) -> None:
    index = Index.of(science.store.nodes())

    result = retrieve_routed(
        {"store": science.store, "index": index, "question": "yield",
         "route": "overview", "communities": ()},
        RetrieveRoutedOptions(),
    )

    assert result["hits"] == ()
