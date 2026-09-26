"""Tests for answering over a walked package, and for refusing to answer over no walk.

The rule of `answer` is inherited and retested here on this prompt: an uncited line is
dropped. The rule this step adds is the one worth the module -- a package that walked
nothing is reported as a gap and never handed to a model, which is what keeps a graph
architecture from decaying into text retrieval when the relations have not been
extracted yet.
"""

from __future__ import annotations

from atlas.llm import Reply
from atlas.steps.graph_answer import GAP, GraphAnswerOptions, graph_answer, relations
from atlas.steps.graph_expand import GraphExpandOptions, expand
from conftest import Fixture

QUESTION = "Does M raise the yield?"
DEFAULTS = GraphAnswerOptions()
POSITIONS = GraphExpandOptions(supports=("supports",), opposes=("disputes",), depth=3)


class StubClient:
    """A client with the signature of `ChatClient.complete`, replaying one canned reply."""

    def __init__(self, text: str) -> None:
        self.reply = Reply(text=text, usage={"total_tokens": 11}, cached=True)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None,
                 system: str | None = None) -> Reply:
        self.prompts.append(prompt)
        return self.reply

    def complete_json(self, prompt: str, schema: dict, *, system: str | None = None) -> dict:
        raise AssertionError("answering asks for prose, not for JSON")


def state_for(science: Fixture, text: str, options: GraphExpandOptions = POSITIONS) -> dict:
    bundle = expand(science.store, [science.nodes["claim"].id], options)
    return {"bundle": bundle, "question": QUESTION, "schema": science.schema,
            "client": StubClient(text)}


def test_an_ungrounded_package_is_a_stated_gap_and_costs_no_call(science: Fixture) -> None:
    state = state_for(science, "anything", GraphExpandOptions(depth=0))

    result = graph_answer(state, DEFAULTS)

    assert result["gap"] == GAP
    assert result["answer"].text == ""
    assert state["client"].prompts == []


def test_only_cited_lines_survive(science: Fixture) -> None:
    claim = science.nodes["claim"].ref
    state = state_for(science, f"M raises the yield under U1. [{claim}]\nIt looks convincing.\n")

    result = graph_answer(state, DEFAULTS)

    assert result["answer"].text == f"M raises the yield under U1. [{claim}]"
    assert result["answer"].citations == (claim,)
    assert result["uncited"] == 1


def test_the_prompt_shows_the_relations_in_the_direction_they_were_asserted(
    science: Fixture,
) -> None:
    state = state_for(science, f"Yes. [{science.nodes['claim'].ref}]")

    graph_answer(state, DEFAULTS)

    [prompt] = state["client"].prompts
    assert "--supports-->" in prompt
    assert "--disputes-->" in prompt
    assert QUESTION in prompt


def test_the_prompt_separates_the_two_sides(science: Fixture) -> None:
    state = state_for(science, f"Yes. [{science.nodes['claim'].ref}]")

    graph_answer(state, DEFAULTS)

    [prompt] = state["client"].prompts
    assert "- supporting:" in prompt
    assert "- opposing:" in prompt


def test_a_package_whose_relations_carry_no_position_says_so(science: Fixture) -> None:
    state = state_for(science, "x", GraphExpandOptions(depth=1))

    graph_answer(state, DEFAULTS)

    [prompt] = state["client"].prompts
    assert "none of the walked relations carries a position" in prompt


def test_relations_are_rendered_from_the_links_not_from_the_walks(science: Fixture) -> None:
    bundle = expand(science.store, [science.nodes["claim"].id], POSITIONS)

    rendered = relations(bundle, science.schema)

    assert len(rendered.splitlines()) == len(bundle.links)


def test_an_answer_the_package_cannot_support_is_reported_as_a_gap(science: Fixture) -> None:
    state = state_for(science, "M raises the yield.\n")

    result = graph_answer(state, DEFAULTS)

    assert result["answer"].text == ""
    assert result["gap"] == "the model wrote nothing the package could support"


def test_what_a_step_concluded_about_the_package_is_put_in_front_of_the_model(
    science: Fixture,
) -> None:
    from atlas.steps.graph_expand import annotate

    state = state_for(science, "anything")
    plain = state["client"]
    graph_answer(state, DEFAULTS)
    assert "About the package as a whole" not in plain.prompts[0]

    noted = state_for(science, "anything")
    noted["bundle"] = annotate(noted["bundle"], {}, ["independent support: 1 distinct source"])
    graph_answer(noted, DEFAULTS)
    assert "- independent support: 1 distinct source" in noted["client"].prompts[0]
