"""An open library for machine-readable markup bound to its sources.

The metamodel lives in `atlas.model`: sources, spans, nodes, links, assertions and the
schema they are written under. It carries no vocabulary of its own -- an ontology is
loaded under it from packs of YAML, a store keeps what was asserted, and a run is a list
of named steps from `atlas.steps`, configured in a file rather than wired in here.
"""
