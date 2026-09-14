"""Answering a question from ranked hits, keeping only what the evidence is cited for.

The rule the library applies to markup applies here to prose. No provenance, no node;
no citation, no statement. The model is shown the hits under the reference each node is
cited by and asked for one statement per line, each ending in the references it rests
on; a line citing nothing, or citing a reference that was not in front of it, is dropped
and counted rather than repaired. An answer therefore comes back shorter than the model
wrote it, sometimes empty, and never with a citation a reader cannot follow into the
store. `keep_cited` is that rule on its own, so a consumer whose prompt and prose are
its own can enforce it without writing it again.

Nothing is asked of the model that can be checked instead: not the source of a node, not
its quote, not which hits were used -- only the text, and the references beside it.

The prompt above is not an option. `keep_cited` enforces the rule that prompt states, so
a configuration free to replace the text would be free to stop asking for the citations
the rule then drops every line for -- an answer that comes back empty with nothing in
the file to say why. A consumer whose prose is its own writes a step and names it
instead, as with the ranking, and keeps `keep_cited`. What a configuration may set is
the system prompt in front of it, which changes the voice and not the contract.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from pydantic import Field

from atlas.llm import ChatClient
from atlas.model import Frozen, Schema
from atlas.steps import State, register
from atlas.steps.retrieve import Hit

PROMPT = """Answer a question from the numbered evidence below, and from nothing else.

Rules:
- Write each statement on its own line, and end every line with the references it rests
  on, each in its own brackets: [one][two], never [one, two].
- A statement with no reference is discarded unread, so cite every one of them.
- Copy a reference exactly as it is written below; do not shorten or invent one.
- If the evidence does not answer the question, write one line saying so, cite the
  closest evidence there is, and add nothing further.
- Answer in the language of the question, in prose, with no preamble and no heading.

Question: {question}

Evidence:
{evidence}
"""

_CITATION = re.compile(r"\[([^\[\]]+)\]")


class Answer(Frozen):
    """An answer that survived its citations being checked, the hits it stands on, its cost."""

    text: str
    citations: tuple[str, ...]
    hits: tuple[Hit, ...]
    usage: Mapping[str, int] = {}
    cached: bool = False


def keep_cited(text: str, known: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    """Keep the lines citing a known reference, and return them with the references made.

    The unit is the line, because that is what the prompt asks a statement to be: a model
    that answers in one uncited paragraph answers nothing, which is the intended outcome
    and not a parsing failure to work around. The cost of that unit is the reason the
    prompt above forbids a heading and asks for prose -- anything written across lines,
    a markdown table above all, loses every row that does not carry its own citation. A
    consumer that wants tables needs another unit here, and another prompt to match it.
    """
    references = set(known)
    kept: list[str] = []
    cited: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        found = [ref for ref in _CITATION.findall(line) if ref in references]
        if not found:
            continue
        kept.append(line.strip())
        cited += [ref for ref in found if ref not in cited]
    return "\n".join(kept), tuple(cited)


def evidence(hits: Iterable[Hit], schema: Schema) -> str:
    """One block per hit: what to cite it by, what to call it, what was claimed, the quotes."""
    return "\n\n".join(
        "\n".join(
            [
                f"[{hit.node.ref}] {schema.label_of(hit.node)} ({hit.node.type})",
                *(f"  {key}: {value}" for key, value in sorted(hit.node.fields.items())),
                *(f"  > {span.text}" for span in hit.node.spans),
            ]
        )
        for hit in hits
    )


class AnswerOptions(Frozen):
    """The system prompt a run puts in front of the model, and nothing else -- see above.

    A system prompt that is present but empty is a line somebody meant to write and did
    not, so it is refused rather than spending a message on nothing; leaving the key out
    is how a run says it wants none.
    """

    system: str | None = Field(None, min_length=1)


@register("answer", requires=("hits", "question", "client", "schema"),
          produces=("answer", "uncited"), options=AnswerOptions)
def answer(state: State, options: AnswerOptions) -> State:
    """Ask the model over the hits, and return the answer with its uncited lines gone."""
    client: ChatClient = state["client"]
    hits: tuple[Hit, ...] = state["hits"]
    prompt = PROMPT.format(question=state["question"], evidence=evidence(hits, state["schema"]))
    reply = client.complete(prompt, system=options.system)
    known = {hit.node.ref: hit for hit in hits}
    text, citations = keep_cited(reply.text, known)
    written = [line for line in reply.text.splitlines() if line.strip()]
    kept = Answer(
        text=text,
        citations=citations,
        hits=tuple(known[ref] for ref in citations),
        usage=reply.usage,
        cached=reply.cached,
    )
    return {"answer": kept, "uncited": len(written) - len(kept.text.splitlines())}
