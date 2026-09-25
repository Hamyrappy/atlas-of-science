"""The rule every architecture obeys: an answer is built from a walked graph, not a list.

Ranking finds where to start. It does not find an answer, and the difference is the
whole point of this step: a hit is a node that shares words with a question, while what
a reader needs is the node, what was found about it, what that rests on, under which
conditions, and who says otherwise. That shape is a walk, so the walk happens here and
its result -- a `Bundle` -- is what every answering step in this library is given.

Three things are guaranteed by this step and are worth stating as guarantees, because
each of them is a way an evidence package silently goes wrong:

**A bundle says whether it is grounded.** `grounded` is false when nothing the ranking
found is touched by any link. That is not an error: it is a corpus whose relations have
not been extracted yet, and the honest response is to say so. `graph_answer` refuses to
write prose over an ungrounded bundle, which is what stops this library from quietly
degrading into text retrieval with a citation stapled on.

**An objection is never dropped for budget.** The predicates a configuration names
under `opposes` are pulled in after the walk, whatever the limit did, together with the
node at the other end. A package that fits its budget by losing the one study that
disagrees is worse than one that admits it is partial.

**Nothing here names a relation.** Which predicates are worth following, which mean
support and which mean dispute are the pack's words and arrive as options. The step
knows only that some relations were pointed at.

`Bundle` lives here rather than in `atlas/model/` by the rule in CLAUDE.md: it is not
asserted, it carries no `schema_version` of its own, and it dies with the state dict.
Every other step that builds a package builds this one, and imports it from here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import Field

from atlas.model import Frozen, Link, Node, Schema
from atlas.steps import State, register
from atlas.steps.retrieve import Hit
from atlas.store import Store
from atlas.walk import DEPTH, Adjacency, Walk, reach

LIMIT = 60
"""How many nodes a package may hold before the walk reports itself partial. Larger
than a ranking's limit and far smaller than a corpus: a package is meant to be read."""


class Bundle(Frozen):
    """One evidence package: what it was built around, what was walked, and what it cost.

    The contract is the same for every architecture, so a generator, a validator and a
    reviewer can be written once. What differs between architectures is how `nodes`,
    `walks` and `reasons` were chosen, and `method` says which one chose them.
    """

    roots: tuple[str, ...]
    nodes: tuple[Node, ...] = ()
    links: tuple[Link, ...] = ()
    walks: tuple[Walk, ...] = ()
    supporting: tuple[str, ...] = ()
    opposing: tuple[str, ...] = ()
    derived: tuple[str, ...] = Field(
        default=(), description="Links nobody claimed, which a materialisation inferred"
    )
    reasons: Mapping[str, str] = {}
    snapshot: str = Field(default="", description="Schema version the package was built under")
    method: str = Field(default="", description="Which architecture's selection produced it")
    partial: bool = False

    @property
    def grounded(self) -> bool:
        """Whether any relation was actually walked, which is what makes this a graph answer."""
        return bool(self.links)

    def node(self, node_id: str) -> Node | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    def refs(self) -> tuple[str, ...]:
        """What a reader may cite, in the order the package lists the nodes."""
        return tuple(node.ref for node in self.nodes)

    def __len__(self) -> int:
        """How big the package is, in nodes, so a run counts it without the step saying so."""
        return len(self.nodes)


class GraphExpandOptions(Frozen):
    """Which relations to walk, how far, and which of them carry a position.

    `follow` empty means every relation the pack declares; naming a few is how a
    configuration says that only some of them explain anything about its questions.
    `supports` and `opposes` are the pack's own predicate names, and the step neither
    knows nor guesses them: a pack that spells them differently says so here.
    """

    depth: int = Field(DEPTH, ge=0)
    limit: int = Field(LIMIT, gt=0)
    follow: tuple[str, ...] = ()
    supports: tuple[str, ...] = ()
    opposes: tuple[str, ...] = ()


@register("graph_expand", requires=("store", "hits"), produces=("bundle",),
          options=GraphExpandOptions)
def graph_expand(state: State, options: GraphExpandOptions) -> State:
    """Walk out from the ranked nodes and return the package an answer may be built from."""
    store: Store = state["store"]
    hits: tuple[Hit, ...] = state["hits"]
    roots = tuple(hit.node.id for hit in hits)
    bundle = expand(
        store,
        roots,
        options,
        reasons={hit.node.id: f"ranked {hit.score:.3f}" for hit in hits},
        snapshot=_snapshot(state),
        method="graph_expand",
        schema=state.get("schema"),
    )
    return {"bundle": bundle}


def expand(
    store: Store,
    roots: Iterable[str],
    options: GraphExpandOptions,
    *,
    reasons: Mapping[str, str] | None = None,
    snapshot: str = "",
    method: str = "",
    adjacency: Adjacency | None = None,
    schema: Schema | None = None,
) -> Bundle:
    """Build a package around some nodes: the shared body of every architecture's retrieval.

    Public because every other selection step in this library ends here. A diffusion, a
    pruned set of paths and a prize-collecting subtree each choose their own roots and
    their own walks, and then all of them need the same closure -- the nodes resolved
    through the store, the objections pulled back in, the package told what it cost.

    `adjacency` is for a store that can answer a bounded neighbourhood better than by
    handing over every link it holds. The caller has then already decided which part of
    the graph is in play; everything after that is the same, which is what keeps one
    package contract across architectures that fetch their graphs very differently.

    `schema`, when given, widens every relation the options name to the relations the
    ontology makes kinds of it (`atlas.reason.ql.relations`): following `bears_on` follows
    `supports` and `disputes`, and an objection named `disputes` is pulled in under every
    relation that is a sub-relation of it. Without a schema the names are taken as written.
    """
    if schema is not None:
        options = widened(options, schema)
    roots = tuple(dict.fromkeys(roots))
    adjacency = Adjacency.of(store.links(), options.follow) if adjacency is None else adjacency
    reached = reach(adjacency, roots, depth=options.depth, limit=options.limit)
    walks = tuple(reached.walks[node_id] for node_id in reached.nodes)
    held = set(reached.walks)
    # Every relation among the nodes held, not only the ones a walk happened to cross.
    # A walk records how a node was first reached, so a relation between two nodes that
    # were both roots is in nobody's walk -- and leaving it out of the package dropped
    # exactly the relations a caller had already decided were the interesting ones.
    kept = {
        link.id for link in adjacency.links.values() if link.src in held and link.dst in held
    }

    # An objection is pulled in whatever the budget did. It is the one thing a package
    # may not lose quietly: a summary built without it reads like a consensus.
    forced = dict(reasons or {})
    for link in adjacency.links.values():
        if link.predicate in options.opposes and {link.src, link.dst} & held:
            kept.add(link.id)
            for end in (link.src, link.dst):
                if end not in held:
                    held.add(end)
                    forced[end] = f"opposing {link.predicate}"

    nodes = store.get_nodes(sorted(held, key=lambda node_id: (node_id not in roots, node_id)))
    links = tuple(adjacency.links[link_id] for link_id in sorted(kept))
    return Bundle(
        roots=roots,
        nodes=nodes,
        links=links,
        walks=walks,
        supporting=tuple(link.id for link in links if link.predicate in options.supports),
        opposing=tuple(link.id for link in links if link.predicate in options.opposes),
        reasons={key: value for key, value in forced.items() if any(n.id == key for n in nodes)},
        snapshot=snapshot,
        method=method,
        partial=reached.partial,
    )


def widened(options: GraphExpandOptions, schema: Schema) -> GraphExpandOptions:
    """The options with every named relation widened to what the ontology makes kinds of it."""
    from atlas.reason.ql import relations

    axioms = schema.every_axiom()
    return options.model_copy(update={
        "follow": relations(axioms, options.follow),
        "supports": relations(axioms, options.supports),
        "opposes": relations(axioms, options.opposes),
    })


def _snapshot(state: State) -> str:
    """What the package was built over, so an answer can be replayed against the same thing."""
    schema = state.get("schema")
    return getattr(schema, "version", "") or ""
