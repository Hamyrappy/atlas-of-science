"""The engines: one per OWL 2 profile, and SHACL for what a record must carry.

| engine | profile | runs over | answers |
|---|---|---|---|
| `rdfs` | RDFS | the data | what the relation signatures and the hierarchy imply |
| `rl` | RL | the data | all OWL 2 RL implies, each with its derivation, and every clash |
| `el` | EL | the ontology | the complete class hierarchy, and which classes are empty |
| `ql` | QL | a query | the certain answers, by rewriting into queries over storage |
| `dl` | DL | the ontology | whether it has a model, and whether each class can |
| `shacl` | -- | the data | what a record lacks or holds that it may not, closed world |

`rdfs` is the `rl` module with its rule set narrowed; `dl` is `tableau`.

Which of them runs over data is the whole design. Only RDFS and RL materialise anything,
because only those profiles cannot conclude that something exists which nobody mentioned:
every fact they derive relates individuals that were already there and stands on facts
that stand on quotes, so the rule "no provenance, no node" survives reasoning. EL and DL
are asked about the ontology; QL answers a query without writing anything.

`engines_of` is how a configuration's engines are read off its steps -- a step names the
engine it runs in its options -- so `atlas variants` can say which engine each
architecture uses without anybody keeping a second list.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ENGINES = ("rdfs", "rl", "el", "ql", "dl", "shacl")

PROFILE_OF = {"rdfs": "RDFS", "rl": "RL", "el": "EL", "ql": "QL", "dl": "DL"}
"""The profile each engine is complete for. SHACL has none: it is not reasoning."""

_BY_STEP: dict[str, str | tuple[str, str]] = {
    "entail": ("engine", "rl"),
    "classify": ("engine", "el"),
    "formal_check": ("engine", "el"),
    "shacl_validate": "shacl",
    "query": "ql",
    "graph_expand_sql": "ql",
    "execute_plan": "ql",
    "compile_units": "el",
}
"""The steps that run an engine: either always the same one, or the one named by an option
(with its default)."""


def engines_of(step: str, options: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """The engine a configured step runs, if it runs one."""
    found = _BY_STEP.get(step)
    if found is None:
        return ()
    if isinstance(found, str):
        return (found,)
    key, default = found
    return (str((options or {}).get(key) or default),)


__all__ = ["ENGINES", "PROFILE_OF", "engines_of"]
