"""Deciding what a claim's form is, and refusing to reason over one whose form is unclear.

"Some X have Y", "usually X have Y" and "all X have Y" are three different claims. One
case establishes the first; counting is the only way to check the second; one
counterexample refutes the third. A store that recorded all three as "X relates to Y"
has thrown away the thing that decides what a counterexample means.

`compile_units` reads the form a `SemanticUnit` node records -- kind, quantifier,
polarity, modality, scope -- and decides one thing about it: **whether it may be reasoned
over**. That is a judgement about completeness, not a question for a model, which is why
it is deterministic and lives here rather than in a prompt.

Three profiles, and the ordering between them is the point:

| Profile | What it means | What may be done with it |
|---|---|---|
| `exact` | Every part of the form is recorded and accepted | Used as a premise |
| `lossy` | Recorded, but a formal reading drops something | Shown and quoted, never a premise |
| `unsupported` | Something needed to read it at all is missing | Kept as what the source said |

**An unknown polarity is `unsupported`, not `lossy`.** That is the one rule worth
arguing about, and it is the one that matters: a claim whose negation scope nobody
recorded can mean either of two opposite things, and treating it as "mostly usable"
is how a refutation becomes a confirmation. An unstated *quantifier* is merely lossy --
the claim is still about the thing it is about.

**The vocabulary is the configuration's.** Which kinds, quantifiers and modalities a run
accepts are named in the manifest, because they are words of a language and of a corpus.
With nothing named, nothing is exact, which is the safe direction to fail in.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Node, Schema
from atlas.steps import State, register
from atlas.steps.graph_expand import Bundle
from atlas.text import normalise

Profile = Literal["exact", "lossy", "unsupported"]
"""How far a unit may be trusted as a formal object: fully, partly, not at all."""


class Unit(Frozen):
    """One claim's form, and the ruling on whether it may be reasoned over."""

    node_id: str
    kind: str = ""
    quantifier: str = ""
    polarity: str = ""
    modality: str = ""
    scope: str = ""
    expression: str = ""
    profile: Profile = "unsupported"
    reason: str = ""

    @property
    def provable(self) -> bool:
        """Whether an inference engine may take this as a premise."""
        return self.profile == "exact"


class CompileUnitsOptions(Frozen):
    """Which type carries a form, which fields hold it, and which values a run accepts.

    Nothing is defaulted into acceptance. `kinds`, `quantifiers` and `modalities` empty
    mean a run accepts none of them, so every unit comes out `unsupported` -- which is
    the right way round for a step whose job is to decide what may be reasoned over.
    """

    type: str = Field("SemanticUnit", min_length=1)
    kinds: tuple[str, ...] = ()
    quantifiers: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ()
    polarities: tuple[str, ...] = ()
    kind_field: str = "kind"
    quantifier_field: str = "quantifier"
    polarity_field: str = "polarity"
    modality_field: str = "modality"
    scope_field: str = "scope"
    expression_field: str = "expression"


@register("compile_units", requires=("store", "schema"),
          produces=("units", "provable", "unsupported_units"), options=CompileUnitsOptions)
def compile_units(state: State, options: CompileUnitsOptions) -> State:
    """Read the form of every unit in the store and rule on what may be done with each."""
    schema: Schema = state["schema"]
    found = tuple(
        read(node, options)
        for node in state["store"].nodes()
        if schema.is_a(node.type, options.type)
    )
    return {
        "units": found,
        "provable": tuple(one.node_id for one in found if one.provable),
        "unsupported_units": sum(one.profile == "unsupported" for one in found),
    }


def read(node: Node, options: CompileUnitsOptions) -> Unit:
    """One node's form, with the profile its completeness earns it."""
    field = node.fields.get
    kind = normalise(field(options.kind_field, ""))
    quantifier = normalise(field(options.quantifier_field, ""))
    polarity = normalise(field(options.polarity_field, ""))
    modality = normalise(field(options.modality_field, ""))
    profile, reason = judge(kind, quantifier, polarity, modality, options)
    return Unit(
        node_id=node.id,
        kind=kind,
        quantifier=quantifier,
        polarity=polarity,
        modality=modality,
        scope=field(options.scope_field, ""),
        expression=field(options.expression_field, ""),
        profile=profile,
        reason=reason,
    )


def judge(
    kind: str, quantifier: str, polarity: str, modality: str, options: CompileUnitsOptions
) -> tuple[Profile, str]:
    """How far this form may be trusted, and why -- in the order the reasons matter.

    Polarity is checked first and hardest. A claim whose negation scope nobody recorded
    can mean either of two opposite things, so it is `unsupported` however complete the
    rest of it is; everything below that is a question of how much a formal reading
    would drop, not of whether it could be read at all.
    """
    if not polarity:
        return "unsupported", "no polarity recorded, so the scope of any negation is unknown"
    if options.polarities and polarity not in options.polarities:
        return "unsupported", f"polarity {polarity!r} is not one this run reads"
    if not kind:
        return "unsupported", "no kind recorded, so there is no form to read"
    if kind not in options.kinds:
        return "unsupported", f"kind {kind!r} is not one this run interprets"
    if not quantifier:
        return "lossy", "no quantifier recorded; a formal reading would have to choose one"
    if options.quantifiers and quantifier not in options.quantifiers:
        return "lossy", f"quantifier {quantifier!r} is not one this run reads formally"
    if modality and modality not in options.modalities:
        return "lossy", f"modality {modality!r} is not one this run reads formally"
    return "exact", "kind, quantifier, polarity and modality are all ones this run reads"


@register("mark_units", requires=("bundle", "units"), produces=("bundle",))
def mark_units(state: State) -> State:
    """Write each unit's form and profile into the package, where the answer will see it.

    The reason a node is in a package is already shown to the model; this puts the form
    of the claim there too, so the answer can say *"this is a universal claim, and this
    counterexample refutes it"* rather than treating three different kinds of statement
    as one. Nothing is filtered: a unit that may not be reasoned over is still what a
    source said, and dropping it would lose the evidence along with the inference.
    """
    bundle: Bundle = state["bundle"]
    forms = {one.node_id: one for one in state["units"]}
    reasons = dict(bundle.reasons)
    for node in bundle.nodes:
        unit = forms.get(node.id)
        if unit is not None:
            reasons[node.id] = _describe(unit, reasons.get(node.id, ""))
    return {"bundle": bundle.model_copy(update={"reasons": reasons})}


def provable_only(units: Iterable[Unit]) -> tuple[str, ...]:
    """The nodes an inference engine may take as premises, and no others.

    Offered so that a configuration wiring a unit layer into `entail` cannot get the
    direction wrong by accident: what is admitted is the exact ones, and everything else
    stays a statement about what a source said.
    """
    return tuple(one.node_id for one in units if one.provable)


def _describe(unit: Unit, before: str) -> str:
    """One line a reader and a model can both use, keeping whatever was already there."""
    form = ", ".join(
        part for part in (unit.kind, unit.quantifier, unit.polarity, unit.modality) if part
    )
    said = f"{form or 'form not recorded'}; {unit.profile}: {unit.reason}"
    return f"{before}; {said}" if before else said
