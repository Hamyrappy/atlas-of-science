"""Checking an answer against the package it was written from, and adding nothing to it.

`graph_answer` already drops a line that cites nothing or cites something that was not
in front of the model. That is a check on the citation. This is the check on the
**answer as a whole**, and it asks three questions the line-by-line rule cannot:

1. Does every citation resolve to a node of the package, in this snapshot?
2. If the package held positions on both sides, does the answer cite both?
3. Did the package say it was partial, and does the reader know?

The second is the one worth the module. An answer built from a package holding a
supporting and an opposing position, which cites only the supporting one, is not a
wrong answer in any way a citation check can see -- every line is cited and every
citation is real. It is an answer that turned a controversy into a consensus by leaving
one side out, and the only place to catch that is here, against the package.

**Nothing is added and nothing is rewritten.** This step produces a verdict and a list
of what was left out. Acting on it -- asking again, showing the omission to a reader,
refusing to answer -- is the configuration's decision, and a step that quietly appended
the missing side would be writing prose nobody checked.
"""

from __future__ import annotations

from pydantic import Field

from atlas.model import Frozen, Link
from atlas.steps import Nothing, State, register
from atlas.steps.answer import Answer
from atlas.steps.graph_expand import Bundle


class Review(Frozen):
    """What is true about one answer, against the package it was written from."""

    cited: tuple[str, ...] = ()
    unknown: tuple[str, ...] = Field(
        default=(), description="Citations that resolve to nothing in the package"
    )
    omitted: tuple[str, ...] = Field(
        default=(), description="Sides of the argument the package held and the answer left out"
    )
    partial: bool = False

    @property
    def complete(self) -> bool:
        """Whether the answer may be shown as it stands."""
        return not self.unknown and not self.omitted


@register("check_answer", requires=("answer", "bundle"), produces=("review", "omissions"),
          options=Nothing)
def check_answer(state: State) -> State:
    """Review the answer against its package: real citations, both sides, an honest budget."""
    answer: Answer = state["answer"]
    bundle: Bundle = state["bundle"]
    known = {node.ref: node.id for node in bundle.nodes}
    cited = {known[ref] for ref in answer.citations if ref in known}
    review = Review(
        cited=answer.citations,
        unknown=tuple(ref for ref in answer.citations if ref not in known),
        omitted=_omitted(bundle, cited),
        partial=bundle.partial,
    )
    return {"review": review, "omissions": len(review.omitted)}


def _omitted(bundle: Bundle, cited: set[str]) -> tuple[str, ...]:
    """The sides the package held that nothing in the answer cites.

    A side counts as cited when the answer cites either end of one of its relations:
    the position itself, or the claim it is about. Requiring both would fail every
    answer that cites the claim once and attributes the two positions to it, which is
    how an answer to this kind of question is actually written.
    """
    sides = {"supporting": bundle.supporting, "opposing": bundle.opposing}
    held = {
        name: [link for link in bundle.links if link.id in ids] for name, ids in sides.items()
    }
    present = {name for name, links in held.items() if any(_touches(link, cited) for link in links)}
    # Only a package that actually holds both sides can have left one out. One-sided
    # evidence answered one-sidedly is a complete answer to the evidence there was.
    if not all(held.values()):
        return ()
    return tuple(sorted(set(held) - present))


def _touches(link: Link, cited: set[str]) -> bool:
    """Whether the answer cites either end of this relation."""
    return bool({link.src, link.dst} & cited)
