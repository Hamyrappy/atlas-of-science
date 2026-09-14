"""An inverted index over the nodes a store projects, kept beside the store.

Ranking needs term counts, and getting them means projecting the whole assertion log,
which is the one expensive read the library has. So the counts are built once and
written where the store says a derived file may go; a process that restarts, or a
second question in the same minute, reads the file instead of the log. The index is a
dictionary -- term, then node id, then count in that node -- because hundreds of
documents do not justify a search engine, and the price of being wrong about that is
one file to delete.

Two things are taken from the library rather than reinvented, and that is the point of
the module: the terms are `atlas.text.tokenise`'s, and the text of a node is
`Node.text()`. An index that tokenised differently from the relocation that placed the
spans would miss nodes whose evidence had been located perfectly well.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from atlas.model import Frozen, Node
from atlas.steps import State, register
from atlas.text import tokenise

ARTIFACT = "index.json"


def signature(nodes: Iterable[Node]) -> str:
    """What an index was built over, so a file describing other nodes is not reused.

    A node id is a content hash, so a corpus that gained, lost or re-extracted one gets
    another signature and a corpus that did not change gets the one already on disk.
    """
    material = "\x00".join(sorted(node.id for node in nodes))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


class Index(Frozen):
    """The postings, the length each score is normalised by, and what it was built over."""

    signature: str
    postings: dict[str, dict[str, int]] = {}
    lengths: dict[str, int] = {}

    @classmethod
    def of(cls, nodes: Iterable[Node]) -> Index:
        """Count the terms of every node, and invert the counts."""
        nodes = tuple(nodes)
        postings: dict[str, dict[str, int]] = {}
        lengths: dict[str, int] = {}
        for node in nodes:
            counts = Counter(tokenise(node.text()))
            lengths[node.id] = sum(counts.values())
            for term, count in counts.items():
                postings.setdefault(term, {})[node.id] = count
        return cls(signature=signature(nodes), postings=postings, lengths=lengths)

    def save(self, path: Path) -> None:
        """Write the index whole, through a temporary file, so a crash leaves no half of one."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".part")
        temporary.write_text(self.model_dump_json(), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> Index:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def __len__(self) -> int:
        """How many nodes are in it, so a run counts the index without the step saying so."""
        return len(self.lengths)


@register("index_nodes", requires=("store",), produces=("index",))
def index_nodes(state: State, *, name: str = ARTIFACT, rebuild: bool = False) -> State:
    """Index the nodes of the store, reusing the artifact on disk while it still fits them."""
    store = state["store"]
    nodes = store.nodes()
    path = store.artifact(name)
    index = None if rebuild else _reusable(path, signature(nodes))
    if index is None:
        index = Index.of(nodes)
        if path is not None:
            index.save(path)
    return {"index": index}


def _reusable(path: Path | None, expected: str) -> Index | None:
    """The stored index if it was built over exactly these nodes, and None otherwise.

    A store with nowhere to keep a file says so by answering None, and the index is then
    built per process rather than reached for in an implementation nobody handed us.
    """
    if path is None or not path.exists():
        return None
    try:
        index = Index.load(path)
    except (ValueError, json.JSONDecodeError):
        return None  # A truncated file is a cache miss, not a failed run.
    return index if index.signature == expected else None
