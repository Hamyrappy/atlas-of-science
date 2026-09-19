"""Answering from a walked package, and refusing to answer from one that was never walked.

`answer` writes prose over a ranked list. This writes it over a `Bundle`, and the
difference is not cosmetic: the model is shown the relations that were traversed, in
the direction they were asserted, and the positions that were found for and against, so
the qualification a scientific answer needs is in front of it rather than reconstructed
from adjacent sentences.

The rule of `answer` is kept exactly: a line that cites nothing, or cites a reference
that was not in front of the model, is dropped and counted. `keep_cited` is imported
rather than rewritten, because two copies of that rule is one copy too many.

One rule is added. **An ungrounded package is not answered.** If the walk found no
relation at all, the run does not quietly fall back to writing prose over whatever the
ranking happened to return -- it produces an empty answer and a `gap` saying what is
missing. That is the difference between a corpus whose relations have not been
extracted and a corpus that has nothing to say, and a system that blurs the two cannot
be trusted on the corpus where it matters.
"""

from __future__ import annotations

from pydantic import Field

from atlas.llm import ChatClient
from atlas.model import Frozen, Schema
from atlas.steps import State, register
from atlas.steps.answer import Answer, keep_cited
from atlas.steps.graph_expand import Bundle

PROMPT = """Answer a question from the evidence package below, and from nothing else.

The package is a walked graph: entries are the things found, relations are how they are
connected, and positions are what was claimed for and against.

Rules:
- Write each statement on its own line, and end every line with the references it rests
  on, each in its own brackets: [one][two], never [one, two].
- A statement with no reference is discarded unread, so cite every one of them.
- Copy a reference exactly as it is written below; do not shorten or invent one.
- Where the package holds positions on both sides, say so and give the conditions each
  one holds under. Do not average them and do not drop the smaller side.
- Where a relation is needed for the answer and the package does not hold it, say that
  it is missing rather than inferring it.
- Answer in the language of the question, in prose, with no preamble and no heading.

Question: {question}

Entries:
{entries}

Relations:
{relations}

Positions:
{positions}
"""

GAP = "the graph holds no relation touching what the question found"
"""What an ungrounded package is reported as. One sentence, because it is shown to a
reader and read by a caller deciding whether to run an extraction."""


def entries(bundle: Bundle, schema: Schema) -> str:
    """One block per node: what to cite it by, what it is, what it says, and why it is here."""
    return "\n\n".join(
        "\n".join(
            [
                f"[{node.ref}] {schema.label_of(node)} ({node.type})",
                *(f"  {key}: {value}" for key, value in sorted(node.fields.items())),
                *(f"  > {span.text}" for span in node.spans),
                *([f"  selected: {bundle.reasons[node.id]}"] if node.id in bundle.reasons else []),
            ]
        )
        for node in bundle.nodes
    )


def relations(bundle: Bundle, schema: Schema) -> str:
    """Every walked relation, written in the direction it was asserted.

    Written from the links rather than from the walks, so a relation that was pulled in
    after the walk -- an objection kept against the budget -- is shown like any other.
    """
    named = {node.id: f"{schema.label_of(node)} [{node.ref}]" for node in bundle.nodes}
    return "\n".join(
        f"- {named.get(link.src, link.src)} --{link.predicate}--> {named.get(link.dst, link.dst)}"
        for link in bundle.links
    )


def positions(bundle: Bundle, schema: Schema) -> str:
    """What the package holds for and against, as two named groups a summary cannot merge."""
    named = {node.id: f"{schema.label_of(node)} [{node.ref}]" for node in bundle.nodes}
    sides = {"supporting": bundle.supporting, "opposing": bundle.opposing}
    lines = [
        f"- {side}: {named.get(link.src, link.src)} -> {named.get(link.dst, link.dst)}"
        for side, ids in sides.items()
        for link in bundle.links
        if link.id in ids
    ]
    return "\n".join(lines) if lines else "- none of the walked relations carries a position"


class GraphAnswerOptions(Frozen):
    """The system prompt in front of the model, and nothing else -- as in `answer`.

    The body of the prompt is not an option for the same reason it is not there: the
    rule that an uncited line is dropped is enforced below, and a configuration free to
    rewrite the instruction asking for citations would be free to make every answer
    come back empty with nothing in the file to say why.
    """

    system: str | None = Field(None, min_length=1)


@register("graph_answer", requires=("bundle", "question", "client", "schema"),
          produces=("answer", "uncited", "gap"), options=GraphAnswerOptions)
def graph_answer(state: State, options: GraphAnswerOptions) -> State:
    """Answer over the walked package, or report the gap if there was no walk to answer over."""
    bundle: Bundle = state["bundle"]
    schema: Schema = state["schema"]
    if not bundle.grounded:
        return {"answer": Answer(text="", citations=(), hits=()), "uncited": 0, "gap": GAP}
    client: ChatClient = state["client"]
    prompt = PROMPT.format(
        question=state["question"],
        entries=entries(bundle, schema),
        relations=relations(bundle, schema),
        positions=positions(bundle, schema),
    )
    reply = client.complete(prompt, system=options.system)
    text, citations = keep_cited(reply.text, bundle.refs())
    written = [line for line in reply.text.splitlines() if line.strip()]
    kept = Answer(
        text=text,
        citations=citations,
        hits=(),
        usage=reply.usage,
        cached=reply.cached,
    )
    gap = "" if text else "the model wrote nothing the package could support"
    return {"answer": kept, "uncited": len(written) - len(kept.text.splitlines()), "gap": gap}
