"""The architectures on offer, read off disk so that something can put them in front of a person.

An architecture in this library is not a class and not a flag. It is a configuration:
a pack or two, a chain of steps, and the options those steps run under. That is the
whole mechanism, and it is what makes fifteen of them tractable -- nothing branches on
which one is in use, because by the time anything runs there is only a pipeline.

What a configuration cannot hold is why anyone would choose it. So each manifest under
`architectures/` carries a `variant:` block beside its steps -- what the architecture
optimises for, what it costs, which family of graph retrieval it belongs to, what it is
worth reading next to -- and this module reads those blocks into a list. That list is
the seam an interface is built on: a screen offering a choice of architecture, a
command listing them, an API returning them. None of those exist here, and all of them
need the same answer, so the answer is a function rather than a screen.

A manifest is a pipeline configuration and is run as one: `atlas run
architectures/a18.yaml corpus/*.pdf` is the whole of "use architecture 18". The
`variant:` key is not reserved by `Pipeline`, so it travels into `Pipeline.meta` and
nothing had to be taught about it.

The numbers under `scores` are the ones the architecture catalogue assigns, carried so
that a list can be ordered the way its author ordered it. They are an engineering
judgement and not a measurement, which is said here and in every spec, because a number
in a table is read as a measurement unless it is stopped.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

from atlas.model import Frozen

SHIPPED = (Path(__file__).parent / "architectures", Path(__file__).parents[1] / "architectures")
"""Where the manifests are: inside the installed package, and beside it in a checkout --
the same two places `atlas.ontology` looks for packs, for the same reason."""

KEY = "variant"


class Variant(Frozen):
    """One architecture, as something that offers a choice has to be able to show it."""

    id: str
    number: int
    title: str
    summary: str
    mechanism: str = ""
    family: str = ""
    optimises: str = ""
    cost: str = ""
    needs: tuple[str, ...] = ()
    scores: dict[str, int] = {}
    questions: tuple[str, ...] = ()
    differs: dict[str, str] = {}
    spec: str = ""
    config: str = ""
    packs: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()

    @property
    def needs_model(self) -> bool:
        """Whether running it means calling a model, which a deployment may not be able to do."""
        return "model" in self.needs


def variants(root: Path | None = None) -> tuple[Variant, ...]:
    """Every architecture on offer, in catalogue order.

    Ordered by number and not by score: the numbering is how the architectures refer to
    each other -- "unlike 18, this one selects paths" -- and a list that reordered them
    would make every one of those sentences a lookup.
    """
    return tuple(sorted((read(path) for path in manifests(root)), key=lambda one: one.number))


def get(identifier: str, root: Path | None = None) -> Variant:
    """One architecture by its id (`a18`) or its number (`18`), or a ValueError listing them."""
    wanted = identifier.strip().lower().removeprefix("a").lstrip("0") or "0"
    for variant in variants(root):
        if variant.id == identifier or str(variant.number) == wanted:
            return variant
    known = ", ".join(f"{one.id} ({one.title})" for one in variants(root))
    raise ValueError(f"unknown architecture {identifier!r}; on offer: {known}")


def manifests(root: Path | None = None) -> tuple[Path, ...]:
    """The manifest files, from the directory given or the first shipped one that exists."""
    for directory in (root,) if root is not None else SHIPPED:
        if directory is not None and directory.is_dir():
            return tuple(sorted(directory.glob("*.yaml")))
    return ()


def read(path: Path) -> Variant:
    """One manifest as a `Variant`: its own block, plus what the configuration around it says.

    The packs and the steps are read off the configuration rather than repeated in the
    block, so a manifest cannot describe a chain it does not run. That is the one piece
    of duplication worth removing here: everything else in the block is prose nothing
    else can derive.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    block = dict(document.get(KEY) or {})
    if not block:
        raise ValueError(f"{path}: an architecture manifest needs a {KEY!r} block")
    return Variant(
        **block,
        config=path.name,
        packs=_listed(document.get("schema")),
        steps=tuple(_named(entry) for entry in document.get("steps") or ()),
    )


def table(chosen: Iterable[Variant] | None = None) -> str:
    """The catalogue as lines a terminal can print: id, title, family, what it optimises."""
    rows = tuple(chosen) if chosen is not None else variants()
    width = max((len(row.id) for row in rows), default=2)
    return "\n".join(
        f"{row.id:<{width}}  {row.title}\n{'':<{width}}  {row.summary}" for row in rows
    )


def _named(entry: str | dict) -> str:
    """The step name of a configuration entry, whether or not it carries options."""
    return entry if isinstance(entry, str) else next(iter(entry))


def _listed(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if not value:
        return ()
    return (value,) if isinstance(value, str) else tuple(value)
