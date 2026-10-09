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

**An exact unit becomes an OWL 2 axiom, and the EL engine reasons over it.** A unit relates
two terms, and a term the ontology has a class for is that class; any other term is a class
of its own, local to the run. Which quantifier words read as *all*, *some* and *none* and
which polarities negate are the configuration's (`readings`, `negative`), and a word nobody
mapped is not translated. Then:

| form | as OWL | is |
|---|---|---|
| all S are O | `SubClassOf(S, O)` | an axiom |
| no S are O, all S are not O | `DisjointClasses(S, O)` | an axiom |
| some S are O | `S ⊓ O` has a member | a claim of existence, checked, never an axiom |
| some S are not O | `S ⊓ ¬O` has a member | the same |

A universal claim is a statement about classes, so it is a terminological axiom and joins
the ontology for the length of the check. An existential claim is about individuals: it is
never added (that would be an EL engine inventing a member, which nothing in this library
does over data), only checked against what the ontology and the universal units imply.

The EL classifier is run twice, over the ontology alone and over the ontology with every
universal unit, and each unit gets one status: `follows` when the ontology alone already
implies it, `contradicted` when the ontology with the other units makes it false -- two
universal claims that leave a term with no possible member, or an existence claim a
disjointness rules out -- and `consistent` otherwise. A contradicted unit names the fewest
other units that contradict it, found by removing units one at a time and keeping only the
ones the contradiction needs. Nothing is dropped for it: a contradiction between two sources
is exactly what a reader must see.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Literal

from pydantic import Field

from atlas.model import Frozen, Node, Schema
from atlas.model.owl import And, Axiom, DisjointClasses, EquivalentClasses, Named, SubClassOf
from atlas.reason.el import Classification, classify
from atlas.reason.profile import profiles
from atlas.steps import State, register
from atlas.steps.graph_expand import Bundle
from atlas.text import normalise

Profile = Literal["exact", "lossy", "unsupported"]
"""How far a unit may be trusted as a formal object: fully, partly, not at all."""

Quantity = Literal["all", "some", "none"]
"""What a quantifier word is read as, when a configuration maps it."""

Form = Literal["", "subclass", "disjoint", "exists", "exists-not"]
"""A translated unit's logical form: two axioms, and two claims that something exists."""

Status = Literal["", "consistent", "follows", "contradicted"]
"""What the EL engine concluded about a translated unit; empty when it was not translated."""

TERM = "unit-term:"
"""The prefix of a class minted for a term the ontology has no class for. Local to a check."""

PROBE = "unit-probe:"
"""The prefix of a class defined only to ask whether an intersection can have a member."""


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
    subject_term: str = ""
    object_term: str = ""
    form: Form = ""
    subject_class: str = ""
    object_class: str = ""
    axiom: str = Field("", description="The unit as OWL 2 functional syntax, if it translates")
    owl_profiles: tuple[str, ...] = Field(
        default=(), description="The OWL 2 profiles its axiom is in"
    )
    status: Status = ""
    against: tuple[str, ...] = Field(
        default=(), description="The fewest other units that, with the ontology, contradict it"
    )

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
    subject_field: str = "subject_term"
    object_field: str = "object_term"
    readings: dict[str, Quantity] = Field(
        default_factory=dict,
        description="Which quantifier words read as all, some or none; others do not translate",
    )
    negative: tuple[str, ...] = Field(default=(), description="Polarities that negate the object")
    reason: bool = Field(True, description="Check the translated units with the EL engine")
    explain_limit: int = Field(
        200, ge=0, description="Above this many universal units a contradiction is not explained"
    )


class Conflict(Frozen):
    """Units that cannot all be true under the ontology, and what shows it."""

    units: tuple[str, ...]
    detail: str


@register("compile_units", requires=("store", "schema"),
          produces=("units", "provable", "unsupported_units", "unit_conflicts"),
          options=CompileUnitsOptions)
def compile_units(state: State, options: CompileUnitsOptions) -> State:
    """Read the form of every unit, translate the exact ones, and let the EL engine judge them."""
    schema: Schema = state["schema"]
    found = tuple(
        translate(read(node, options), schema, options)
        for node in state["store"].nodes()
        if schema.is_a(node.type, options.type)
    )
    conflicts: tuple[Conflict, ...] = ()
    if options.reason:
        found, conflicts = judge_all(found, schema, options.explain_limit)
    return {
        "units": found,
        "provable": tuple(one.node_id for one in found if one.provable),
        "unsupported_units": sum(one.profile == "unsupported" for one in found),
        "unit_conflicts": conflicts,
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
        subject_term=field(options.subject_field, "").strip(),
        object_term=field(options.object_field, "").strip(),
    )


def translate(unit: Unit, schema: Schema, options: CompileUnitsOptions) -> Unit:
    """The unit with its OWL 2 reading, if it is exact and its form maps to one."""
    if not unit.provable or not unit.subject_term or not unit.object_term:
        return unit
    quantity = options.readings.get(unit.quantifier)
    if quantity is None:
        return unit
    negated = unit.polarity in options.negative
    subject, obj = _term(unit.subject_term, schema), _term(unit.object_term, schema)
    if quantity == "some":
        form: Form = "exists-not" if negated else "exists"
    else:
        form = "subclass" if (quantity == "all") != negated else "disjoint"
    translated = unit.model_copy(update={"form": form, "subject_class": subject,
                                         "object_class": obj})
    axiom = _axiom(translated)
    if axiom is None:
        inner = f"ObjectComplementOf({obj})" if negated else obj
        return translated.model_copy(
            update={"axiom": f"has a member: ObjectIntersectionOf({subject} {inner})"})
    return translated.model_copy(update={"axiom": axiom.text(), "owl_profiles": profiles([axiom])})


def _term(text: str, schema: Schema) -> str:
    """The ontology's class for a term, or a class of the run's own for one it has no word for."""
    found = schema.find_type(text)
    return found.name if found is not None else f"{TERM}{normalise(text)}"


def judge_all(
    units: Sequence[Unit], schema: Schema, explain_limit: int = 200
) -> tuple[tuple[Unit, ...], tuple[Conflict, ...]]:
    """Every translated unit with its status, and the contradictions among them.

    One EL classification over the ontology alone says what already follows; one over the
    ontology with every universal unit says what is contradicted. The probes -- a class
    defined as the intersection a unit is about -- are definitions, so adding them changes
    nothing either classification concludes about any other class.
    """
    translated = [one for one in units if one.form]
    if not translated:
        return tuple(units), ()
    base = list(schema.every_axiom())
    probes = [_probe(one) for one in translated]
    universal = {one.node_id: axiom for one in translated if (axiom := _axiom(one)) is not None}
    names = sorted({name for one in translated for name in (one.subject_class, one.object_class)})

    alone = classify([*base, *probes], names)
    together = classify([*base, *probes, *universal.values()], names)

    def without(unit: Unit) -> Callable[[Iterable[str]], bool]:
        def test(kept: Iterable[str]) -> bool:
            return _false(unit, classify([*base, *probes, *(universal[one] for one in kept)],
                                         names))
        return test

    judged: list[Unit] = []
    for unit in units:
        if not unit.form:
            judged.append(unit)
        elif _false(unit, together):
            against: tuple[str, ...] = ()
            if len(universal) <= explain_limit:
                against = tuple(one for one in _fewest(sorted(universal), without(unit))
                                if one != unit.node_id)
            judged.append(unit.model_copy(update={"status": "contradicted", "against": against}))
        elif _true(unit, alone):
            judged.append(unit.model_copy(update={"status": "follows"}))
        else:
            judged.append(unit.model_copy(update={"status": "consistent"}))
    return tuple(judged), _conflicts(judged)


def _axiom(unit: Unit) -> Axiom | None:
    """The terminological axiom a universal unit states; an existence claim states none."""
    subject, obj = Named(name=unit.subject_class), Named(name=unit.object_class)
    if unit.form == "subclass":
        return SubClassOf(sub=subject, sup=obj)
    if unit.form == "disjoint":
        return DisjointClasses(classes=(subject, obj))
    return None


def _probe(unit: Unit) -> Axiom:
    """A class defined as the intersection of the unit's two terms, to ask whether it can hold."""
    return EquivalentClasses(classes=(
        Named(name=f"{PROBE}{unit.node_id}"),
        And(operands=(Named(name=unit.subject_class), Named(name=unit.object_class))),
    ))


def _false(unit: Unit, found: Classification) -> bool:
    """Whether the classification makes the unit false.

    A universal claim presupposes its subject has members, as a scientific claim about a
    kind of thing does; two universals that together leave the subject empty cannot both be
    what their sources meant, which is the contradiction reported.
    """
    if unit.subject_class in found.unsatisfiable:
        return True
    if unit.form == "exists":
        return f"{PROBE}{unit.node_id}" in found.unsatisfiable
    if unit.form == "exists-not":
        return unit.object_class in found.subsumers.get(unit.subject_class, frozenset())
    return False


def _true(unit: Unit, found: Classification) -> bool:
    """Whether the ontology alone already implies the unit."""
    if unit.form == "subclass":
        return unit.object_class in found.subsumers.get(unit.subject_class, frozenset())
    if unit.form == "disjoint":
        return f"{PROBE}{unit.node_id}" in found.unsatisfiable
    return False


def _fewest(candidates: Sequence[str], broken: Callable[[Iterable[str]], bool]) -> tuple[str, ...]:
    """The fewest candidates the failure still needs: each is removed, and kept out if it can be."""
    kept = list(candidates)
    for one in candidates:
        trial = [other for other in kept if other != one]
        if broken(trial):
            kept = trial
    return tuple(kept)


def _conflicts(units: Sequence[Unit]) -> tuple[Conflict, ...]:
    """One conflict per set of units that cannot all hold, however many of them it names."""
    seen: dict[tuple[str, ...], Conflict] = {}
    for unit in units:
        if unit.status != "contradicted":
            continue
        together = tuple(sorted({unit.node_id, *unit.against}))
        if together in seen:
            continue
        if not unit.against:
            detail = f"the ontology rules out {unit.axiom}"
        elif unit.form in ("subclass", "disjoint"):
            detail = f"together these leave {unit.subject_class} with no possible member"
        else:
            detail = f"together these rule out {unit.axiom}"
        seen[together] = Conflict(units=together, detail=detail)
    return tuple(seen.values())


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
    if unit.axiom:
        said += f"; as OWL: {unit.axiom}"
    if unit.status == "follows":
        said += "; the ontology already implies it"
    elif unit.status == "contradicted":
        said += ("; contradicted by the ontology" if not unit.against else
                 f"; contradicted together with {', '.join(unit.against)}")
    return f"{before}; {said}" if before else said
