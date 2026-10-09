"""The OWL 2 RL engine: rules over data, every consequence with its derivation.

The rules under test are the ones that make reasoning over extracted data safe. Nothing is
invented -- an axiom with an existential on the right is left out and named. Every derived
fact carries the rule, its premises and the axiom behind it. A contradiction is a clash
with its premises, not an exception. A consequence that follows two ways survives losing
one of them, and two that support each other in a circle fall together.
"""

from __future__ import annotations

from atlas.model.owl import (
    And,
    Cardinality,
    DisjointClasses,
    DisjointProperties,
    Domain,
    HasCharacteristic,
    InverseProperties,
    Only,
    Property,
    Range,
    Some,
    SubClassOf,
    SubPropertyOf,
    named,
)
from atlas.reason.facts import SAME, TYPE, Fact
from atlas.reason.rl import RDFS, reason, supported


def fact(fact_id: str, subject: str, predicate: str, obj: str) -> Fact:
    return Fact(id=fact_id, subject=subject, predicate=predicate, object=obj)


def derived(closure) -> set[tuple[str, str, str]]:  # noqa: ANN001
    return {one.triple for one in closure.derived()}


def r(name: str, inverse: bool = False) -> Property:
    return Property(name=name, inverse=inverse)


def test_domain_and_range_type_what_a_relation_touches() -> None:
    closure = reason([fact("l", "a", "supports", "p")], [
        Domain(property="supports", domain=named("EvidenceLine")),
        Range(property="supports", range=named("Proposition")),
    ])
    assert {("a", TYPE, "EvidenceLine"), ("p", TYPE, "Proposition")} <= derived(closure)


def test_every_consequence_names_its_rule_its_premises_and_its_axiom() -> None:
    closure = reason([fact("ab", "a", "part_of", "b"), fact("bc", "b", "part_of", "c")],
                     [HasCharacteristic(property="part_of", characteristic="transitive")])
    [why] = [one for one in closure.derivations if one.rule_id == "prp-trp"]
    assert (why.rule, why.premises) == ("transitive", ("ab", "bc"))
    assert why.axiom == "TransitiveObjectProperty(part_of)"


def test_an_existential_on_the_right_is_left_out_because_it_would_invent_an_individual() -> None:
    invents = SubClassOf(sub=named("Result"), sup=Some(property=r("produced_by"),
                                                       filler=named("Study")))
    closure = reason([fact("n", "x", TYPE, "Result")], [invents])
    assert closure.ignored == (invents,)
    assert derived(closure) == set()


def test_a_disjointness_turns_a_mistyped_relation_into_a_clash_with_both_premises() -> None:
    closure = reason([fact("n", "d", TYPE, "Dataset"), fact("l", "d", "supports", "p")], [
        Domain(property="supports", domain=named("EvidenceLine")),
        DisjointClasses(classes=(named("EvidenceLine"), named("Dataset"))),
    ])
    [clash] = closure.clashes
    assert clash.rule_id == "cax-dw" and "n" in clash.premises
    assert not closure.consistent


def test_two_disjoint_relations_between_one_pair_are_a_clash() -> None:
    closure = reason([fact("s", "line", "supports", "p"), fact("d", "line", "disputes", "p")],
                     [DisjointProperties(properties=(r("supports"), r("disputes")))])
    assert [one.rule_id for one in closure.clashes] == ["prp-pdw"]


def test_an_asymmetric_relation_asserted_both_ways_is_a_clash() -> None:
    closure = reason([fact("ab", "a", "depends", "b"), fact("ba", "b", "depends", "a")],
                     [HasCharacteristic(property="depends", characteristic="asymmetric")])
    assert [one.rule_id for one in closure.clashes] == ["prp-asyp"]


def test_a_chain_with_an_inverse_carries_a_run_s_conditions_to_its_results() -> None:
    closure = reason(
        [fact("y", "run", "yielded", "res"), fact("u", "run", "under_condition", "hot")],
        [SubPropertyOf(sub=(r("yielded", True), r("under_condition")), sup=r("obtained_under"))],
    )
    assert ("res", "obtained_under", "hot") in derived(closure)


def test_a_sub_property_written_against_an_inverse_is_read_backwards() -> None:
    closure = reason([fact("l", "a", "part_of", "b")],
                     [InverseProperties(first="part_of", second="has_part")])
    assert ("b", "has_part", "a") in derived(closure)


def test_an_existential_on_the_left_types_by_what_a_neighbour_is() -> None:
    given = [fact("l", "line", "disputes", "p"), fact("n", "line", TYPE, "EvidenceLine")]
    closure = reason(given, [
        SubClassOf(sub=Some(property=r("disputes", True), filler=named("EvidenceLine")),
                   sup=named("ContestedProposition")),
    ])
    assert ("p", TYPE, "ContestedProposition") in derived(closure)


def test_a_universal_on_the_right_types_everything_it_reaches() -> None:
    closure = reason([fact("n", "rep", TYPE, "Replication"), fact("l", "rep", "of", "z")],
                     [SubClassOf(sub=named("Replication"),
                                 sup=Only(property=r("of"), filler=named("Result")))])
    assert ("z", TYPE, "Result") in derived(closure)


def test_at_most_one_makes_two_values_the_same_individual() -> None:
    closure = reason([fact("n", "s", TYPE, "Single"), fact("a", "s", "about", "u1"),
                      fact("b", "s", "about", "u2")],
                     [SubClassOf(sub=named("Single"),
                                 sup=Cardinality(bound="max", count=1, property=r("about")))])
    assert ("u1", SAME, "u2") in derived(closure) and ("u2", SAME, "u1") in derived(closure)


def test_an_identity_is_off_unless_a_configuration_names_the_relation() -> None:
    given = [fact("s", "x", "same_as", "y"), fact("n", "x", TYPE, "Result")]
    assert ("y", TYPE, "Result") not in derived(reason(given, []))
    assert ("y", TYPE, "Result") in derived(reason(given, [], identity=("same_as",)))


def test_an_intersection_on_the_left_needs_every_part() -> None:
    axiom = SubClassOf(sub=And(operands=(named("Result"), Some(property=r("observed_under"),
                                                               filler=named("Context")))),
                       sup=named("ConditionedResult"))
    alone = reason([fact("n", "r", TYPE, "Result"), fact("l", "r", "observed_under", "c")], [axiom])
    assert ("r", TYPE, "ConditionedResult") not in derived(alone)
    typed = reason([fact("n", "r", TYPE, "Result"), fact("l", "r", "observed_under", "c"),
                    fact("m", "c", TYPE, "Context")], [axiom])
    assert ("r", TYPE, "ConditionedResult") in derived(typed)


def test_the_rdfs_engine_keeps_the_four_rdfs_rules_and_nothing_else() -> None:
    axioms = [Domain(property="p", domain=named("A")),
              HasCharacteristic(property="p", characteristic="symmetric")]
    closure = reason([fact("l", "x", "p", "y")], axioms, rules=RDFS)
    assert derived(closure) == {("x", TYPE, "A")}
    assert len(closure.ignored) == 1


def test_a_closure_cut_short_says_so() -> None:
    chain = [fact(f"l{i}", str(i), "p", str(i + 1)) for i in range(6)]
    closure = reason(chain, [HasCharacteristic(property="p", characteristic="transitive")],
                     rounds=1)
    assert not closure.finished


def test_two_consequences_that_support_each_other_fall_together() -> None:
    closure = reason([fact("ab", "a", "part_of", "b")],
                     [InverseProperties(first="part_of", second="has_part")])
    assert supported(closure, {"ab"}) == set()
    assert supported(closure, ()) == {"ab", *(one.id for one in closure.derived())}
