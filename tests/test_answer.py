"""Tests for the answering step, driven by a stub client that replays a canned reply.

What is under test is the rule and not the prose: a line keeps its place in the answer
only if it cites a node that was actually in front of the model. `keep_cited` is tested
on its own as well, because it is offered to consumers that write their own prompt, and
a rule with one caller is not a rule.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from atlas.llm import Reply
from atlas.model import (
    Agent,
    Assertion,
    FieldDef,
    Node,
    Schema,
    Segment,
    Source,
    Span,
    TypeDef,
)
from atlas.pipeline import Pipeline
from atlas.steps import get
from atlas.steps.answer import PROMPT, Answer, AnswerOptions, answer, evidence, keep_cited
from atlas.steps.retrieve import Hit
from atlas.store.memory import MemoryStore

TEXT = "Точность распознавания составила 0,94 против 0,81 у базового решения.\n"
VERSION = "0" * 12
SOURCE = Source(id="doc-1", origin="corpus/doc-1.txt", segments=(Segment(number=1, text=TEXT),))
SCHEMA = Schema(
    version=VERSION,
    types=(TypeDef(name="Thing", fields=(FieldDef(name="name"),), label_field="name"),),
)
QUESTION = "Какая точность распознавания?"
DEFAULTS = AnswerOptions()
PACK = """
types:
  - name: Thing
    description: Anything the text names.
    fields: [name]
"""


def node(node_id: str, quote: str, **fields: str) -> Node:
    start = TEXT.index(quote)
    return Node(
        id=node_id,
        type="Thing",
        spans=(Span.of(SOURCE, 1, start, start + len(quote)),),
        schema_version=VERSION,
        fields=fields,
    )


RESULT = node("9f2c41ab77de", "Точность распознавания составила 0,94", name="точность")
BASELINE = node("3d0e55cc12aa", "0,81 у базового решения", name="базовое решение")
HITS = (Hit(node=RESULT, score=0.5), Hit(node=BASELINE, score=0.2))


class StubClient:
    """A client with the signature of `ChatClient.complete`, replaying one canned reply."""

    def __init__(self, text: str) -> None:
        self.reply = Reply(text=text, usage={"total_tokens": 41}, cached=True)
        self.prompts: list[str] = []
        self.systems: list[str | None] = []

    def complete(self, prompt: str, *, schema: dict | None = None,
                 system: str | None = None) -> Reply:
        self.prompts.append(prompt)
        self.systems.append(system)
        return self.reply

    def complete_json(self, prompt: str, schema: dict, *, system: str | None = None) -> dict:
        raise AssertionError("the answering step asks for prose, not for JSON")


def state_for(text: str) -> dict:
    return {"client": StubClient(text), "hits": HITS, "question": QUESTION, "schema": SCHEMA}


def test_only_cited_statements_survive() -> None:
    reply = (
        f"Точность распознавания составила 0,94. [{RESULT.ref}]\n"
        "Работа выглядит убедительной.\n"
        "Есть и вторая оценка. [doc-1#ffffff]\n"
    )

    state = answer(state_for(reply), DEFAULTS)

    result: Answer = state["answer"]
    assert result.text == f"Точность распознавания составила 0,94. [{RESULT.ref}]"
    assert result.citations == (RESULT.ref,)
    assert [hit.node.id for hit in result.hits] == [RESULT.id]
    assert state["uncited"] == 2


def test_citations_keep_the_order_they_were_made_in() -> None:
    reply = f"База. [{BASELINE.ref}]\nТочность. [{RESULT.ref}][{BASELINE.ref}]\n"

    result = answer(state_for(reply), DEFAULTS)["answer"]

    assert result.citations == (BASELINE.ref, RESULT.ref)
    assert result.hits[0].node.id == BASELINE.id


def test_an_uncited_answer_is_an_empty_answer() -> None:
    state = answer(state_for("Точность 0,94."), DEFAULTS)

    assert state["answer"].text == ""
    assert state["answer"].citations == ()
    assert state["uncited"] == 1


def test_the_prompt_carries_the_question_the_references_and_the_quotes() -> None:
    state = state_for(f"Да. [{RESULT.ref}]")

    answer(state, DEFAULTS)

    [prompt] = state["client"].prompts
    assert QUESTION in prompt
    assert f"[{RESULT.ref}]" in prompt
    assert RESULT.spans[0].text in prompt
    assert PROMPT.splitlines()[0] in prompt


def test_the_evidence_names_a_node_by_its_label_and_not_by_its_id() -> None:
    rendered = evidence(HITS, SCHEMA)

    assert f"[{RESULT.ref}] точность (Thing)" in rendered
    assert f"  > {RESULT.spans[0].text}" in rendered
    assert RESULT.id not in rendered


def test_what_the_reply_cost_travels_with_the_answer() -> None:
    result = answer(state_for(f"Да. [{RESULT.ref}]"), DEFAULTS)["answer"]

    assert result.usage == {"total_tokens": 41}
    assert result.cached is True


def test_the_citation_rule_stands_on_its_own() -> None:
    """A consumer with its own prompt enforces the same rule without rewriting it."""
    text = "One. [a]\nTwo.\n\nThree. [b][a]\nFour. [c]\n"

    kept, cited = keep_cited(text, ("a", "b"))

    assert kept == "One. [a]\nThree. [b][a]"
    assert cited == ("a", "b")


def test_a_reply_with_no_hits_in_front_of_it_cites_nothing() -> None:
    assert keep_cited("Ничего не найдено. [doc-1#abcdef]", ()) == ("", ())


def test_the_step_declares_what_it_reads_and_adds() -> None:
    step = get("answer")

    assert step.requires == ("hits", "question", "client", "schema")
    assert step.produces == ("answer", "uncited")
    assert step.options is AnswerOptions


def test_the_system_prompt_a_run_configures_reaches_the_client() -> None:
    state = state_for(f"Да. [{RESULT.ref}]")

    answer(state, AnswerOptions(system="Отвечай коротко."))

    assert state["client"].systems == ["Отвечай коротко."]


def test_an_option_the_step_does_not_take_is_refused_when_the_file_is_read(
    write_config: Callable[[str, str], Path]
) -> None:
    """`prompt` is the one a consumer reaches for, and the one the step does not offer."""
    steps = "  - {answer: {prompt: Ответь на вопрос.}}\n"

    with pytest.raises(ValueError, match=re.escape(
        "step 'answer': unknown option 'prompt'. It takes system: str | None = None"
    )):
        Pipeline.from_config(write_config(PACK, steps))


def test_a_system_prompt_written_and_left_empty_is_refused(
    write_config: Callable[[str, str], Path]
) -> None:
    steps = '  - {answer: {system: ""}}\n'

    with pytest.raises(ValueError, match=re.escape("step 'answer': option 'system':")):
        Pipeline.from_config(write_config(PACK, steps))


def test_a_node_carries_the_reference_it_is_cited_by() -> None:
    """The citation is the library's reference, minted by nothing here."""
    assert RESULT.ref == "doc-1#9f2c41"
    assert RESULT.ref in evidence(HITS, SCHEMA)


def test_the_three_shipped_steps_chain_into_an_answer() -> None:
    """Index, rank, answer: the keys each one declares are the keys the next one reads."""
    store = MemoryStore()
    store.add_source(SOURCE)
    agent = Agent(id="agent-m", kind="model", label="extractor")
    store.assert_(Assertion(id="a-1", agent=agent, at="2025-01-01T00:00:00+00:00", target=RESULT))
    pipeline = Pipeline(
        SCHEMA, tuple((get(name), {}) for name in ("index_nodes", "retrieve", "answer"))
    )

    state = pipeline.run_state(
        pipeline.initial(
            store=store, question=QUESTION, client=StubClient(f"Да, 0,94. [{RESULT.ref}]")
        )
    )

    assert len(state["index"]) == 1
    assert len(state["hits"]) == 1
    assert state["answer"].citations == (RESULT.ref,)
