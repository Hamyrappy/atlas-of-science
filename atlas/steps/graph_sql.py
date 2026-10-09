"""Building the evidence package out of queries, for a store that can answer them.

`graph_expand` reads every link the store holds and walks them in the process. That is
the right shape for hundreds of documents and the wrong one once the store is large:
the walk visits a few dozen nodes and the read that preceded it visited the corpus.

This step does the same thing the other way round. It asks the store for the bounded
neighbourhood of the seeds and for the links inside it, builds an adjacency over just
that, and then hands it to the same `expand` as everything else -- so the package that
comes out is the same object, with the same guarantees, chosen by a query instead of by
a scan. The architecture that uses it is a relational one; the contract is the shared
one, and nothing downstream can tell which way the graph arrived.

**A store that cannot do this is told so rather than made to.** The step asks for `reach`
with `getattr`; a store without it gets a `ValueError` naming what it is missing. That
is deliberately not a silent fallback to reading every link: a configuration that names
this step is asking for the relational route, and quietly giving it the other one would
mean the thing being measured is not the thing that ran.

**The objection still survives the budget**, and here it costs a second query:
`links_touching` finds the relations of the named opposing kinds that touch anything in
the neighbourhood, including the ones whose other end the walk never reached. Those are
precisely the ones a bounded query would otherwise lose, which is why the query exists.

**The ontology rewrites what is asked for, as OWL 2 QL does.** A relation named in the
options is widened to every relation the ontology makes a kind of it before a query is
written -- `disputes` also fetches whatever is declared a sub-relation of it, or the inverse
of one -- so the store is asked, in plain SQL, for everything the ontology implies about the
neighbourhood and not only what was spelled the way the configuration spelled it. That is
ontology-based data access in its smallest form: the ontology works on the query, and the
database never learns it exists.
"""

from __future__ import annotations

from atlas.steps import State, register
from atlas.steps.graph_expand import GraphExpandOptions, expand, widened
from atlas.steps.retrieve import Hit
from atlas.walk import Adjacency


@register("graph_expand_sql", requires=("store", "hits"), produces=("bundle",),
          options=GraphExpandOptions)
def graph_expand_sql(state: State, options: GraphExpandOptions) -> State:
    """Fetch the neighbourhood of the ranked nodes from the store, and package it."""
    store = state["store"]
    reach = getattr(store, "reach", None)
    among = getattr(store, "links_among", None)
    touching = getattr(store, "links_touching", None)
    if reach is None or among is None or touching is None:
        raise ValueError(
            f"{type(store).__name__} cannot answer a bounded neighbourhood: "
            "'graph_expand_sql' needs a store offering reach, links_among and "
            "links_touching, such as 'sqlite'. Use 'graph_expand' to walk the links "
            "in the process instead."
        )
    hits: tuple[Hit, ...] = state["hits"]
    schema = state.get("schema")
    options = widened(options, schema) if schema is not None else options
    roots = tuple(dict.fromkeys(hit.node.id for hit in hits))
    reached = reach(roots, depth=options.depth, limit=options.limit)
    ids = tuple(reached.distances)

    links = list(among(ids))
    if options.opposes:
        # The relation whose other end the walk never reached is exactly the one a
        # bounded query loses, so it is fetched on purpose rather than hoped for.
        links += [link for link in touching(ids, options.opposes)
                  if link.id not in {one.id for one in links}]
    adjacency = Adjacency.of(links, options.follow)

    bundle = expand(
        store,
        roots,
        options,
        reasons={hit.node.id: f"ranked {hit.score:.3f}" for hit in hits},
        snapshot=getattr(state.get("schema"), "version", "") or "",
        method="graph_expand_sql",
        adjacency=adjacency,
    )
    return {"bundle": bundle.model_copy(update={"partial": bundle.partial or reached.partial})}
