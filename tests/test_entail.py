"""Tests for computing what the pack's relation axioms imply, and for remembering why.

The four rules the module states are the four under test. Nothing is written to the
store. Every derived link carries its premises and its rule. Only admitted relations are
reasoned over. And a retraction is computed: what falls is separated from what still
follows on other grounds, because reporting the second as lost overstates the damage.
"""

from __future__ import annotations

from atlas.model import (
    Agent,
    Assertion,
    FieldDef,
    Link,
    Node,
    PredicateDef,
    Schema,
    Segment,
    Source,
    Span,
    TypeDef,
)
from atlas.steps.entail import (
    DERIVED,
    EntailOptions,
    close,
    entail,
    graph_expand_entailed,
    invalidated,
    supported,
)
from atlas.steps.graph_expand import GraphExpandOptions
from atlas.steps.retrieve import Hit
from atlas.store.memory import MemoryStore

TEXT = "a is part of b, b is part of c, and d is next to e\n"
SOURCE = Source(id="s", origin="s.txt", segments=(Segment(number=1, text=TEXT),))
SCHEMA = Schema(
    version="0" * 12,
    types=(TypeDef(name="Thing", fields=(FieldDef(name="name"),), label_field="name"),),
    predicates=(
        PredicateDef(name="part_of", domain="Thing", range="Thing",
                     characteristics=("transitive",)),
        PredicateDef(name="has_part", domain="Thing", range="Thing", inverse_of="part_of"),
        PredicateDef(name="next_to", domain="Thing", range="Thing",
                     characteristics=("symmetric",)),
        PredicateDef(name="mentions", domain="Thing", range="Thing"),
    ),
)


def node(name: str, at: int) -> Node:
    return Node(id=name * 16, type="Thing", fields={"name": name},
                spans=(Span.of(SOURCE, 1, at, at + 1),), schema_version=SCHEMA.version)


def link(link_id: str, predicate: str, src: str, dst: str) -> Link:
    return Link(id=link_id, predicate=predicate, src=src * 16, dst=dst * 16,
                spans=(Span.of(SOURCE, 1, 0, 1),), schema_version=SCHEMA.version)


def store_with(*links: Link) -> MemoryStore:
    store = MemoryStore()
    store.add_source(SOURCE)
    agent = Agent(id="run", kind="run")
    targets = [node(name, index) for index, name in enumerate("abcde")]
    for index, target in enumerate([*targets, *links]):
        store.assert_(Assertion(id=f"x{index}", agent=agent,
                                at="2026-01-01T00:00:00+00:00", target=target))
    return store


PART_AB = link("ab", "part_of", "a", "b")
PART_BC = link("bc", "part_of", "b", "c")
NEXT_DE = link("de", "next_to", "d", "e")


def test_a_transitive_chain_produces_the_link_nobody_asserted() -> None:
    closure = close([PART_AB, PART_BC], SCHEMA)

    [derived] = [one for one in closure.links if one.predicate == "part_of"]
    assert (derived.src, derived.dst) == ("a" * 16, "c" * 16)
    assert derived.fields[DERIVED] == "transitive"
    assert closure.finished


def test_a_derived_link_carries_its_premises_and_its_rule() -> None:
    closure = close([PART_AB, PART_BC], SCHEMA)

    transitive = next(one for one in closure.derivations if one.rule == "transitive")
    assert transitive.premises == ("ab", "bc")
    assert transitive.schema_version == SCHEMA.version


def test_a_derived_link_stands_on_the_evidence_of_its_premises() -> None:
    closure = close([PART_AB, PART_BC], SCHEMA)

    # No text says the consequence, so it carries the spans of what it came from rather
    # than a span invented for it.
    assert all(one.spans == PART_AB.spans for one in closure.links if one.predicate == "part_of")


def test_a_symmetric_relation_is_derived_the_other_way_round() -> None:
    closure = close([NEXT_DE], SCHEMA)

    [derived] = closure.links
    assert (derived.predicate, derived.src, derived.dst) == ("next_to", "e" * 16, "d" * 16)
    assert [one.rule for one in closure.derivations if one.link_id == derived.id] == ["symmetric"]


def test_an_inverse_is_derived_from_either_side_of_the_pair() -> None:
    closure = close([PART_AB], SCHEMA)

    assert any(one.predicate == "has_part" and one.src == "b" * 16 for one in closure.links)


def test_a_relation_with_no_characteristic_implies_nothing() -> None:
    closure = close([link("m", "mentions", "a", "b")], SCHEMA)

    assert closure.links == ()


def test_nothing_is_written_to_the_store() -> None:
    store = store_with(PART_AB, PART_BC)
    before = store.assertions()

    entail({"store": store, "schema": SCHEMA}, EntailOptions())

    assert store.assertions() == before
    assert len(store.links()) == 2


def test_only_the_admitted_relations_are_reasoned_over() -> None:
    store = store_with(PART_AB, PART_BC, NEXT_DE)

    result = entail({"store": store, "schema": SCHEMA},
                    EntailOptions(premises=("part_of",)))

    assert all(one.predicate != "next_to" for one in result["derived"])


def test_a_closure_that_did_not_settle_says_so() -> None:
    store = store_with(PART_AB, PART_BC, link("cd", "part_of", "c", "d"))

    result = entail({"store": store, "schema": SCHEMA}, EntailOptions(rounds=1))

    assert not result["closure_finished"]


def test_a_cycle_does_not_derive_a_thing_being_part_of_itself() -> None:
    closure = close([PART_AB, link("ba", "part_of", "b", "a")], SCHEMA)

    assert all(one.src != one.dst for one in closure.links)


def a_to_c(closure) -> str:
    """The id of the derived `part_of` from a to c, which two chains can reach."""
    return next(one.id for one in closure.links
                if one.predicate == "part_of" and one.src == "a" * 16 and one.dst == "c" * 16)


def test_a_consequence_that_follows_two_ways_survives_losing_one_of_them() -> None:
    # Two chains to the same consequence: a -> b -> c, and a -> d -> c.
    closure = close(
        [PART_AB, PART_BC, link("ad", "part_of", "a", "d"), link("dc", "part_of", "d", "c")],
        SCHEMA,
    )

    fallen, standing = invalidated(closure, {"bc"})

    assert a_to_c(closure) in {one.link_id for one in standing}
    assert a_to_c(closure) not in {one.link_id for one in fallen}
    assert all(one.rests_on({"bc"}) for one in [*fallen, *standing])


def test_a_retraction_that_takes_the_only_ground_leaves_the_consequence_fallen() -> None:
    closure = close([PART_AB, PART_BC], SCHEMA)

    fallen, standing = invalidated(closure, {"bc"})

    assert a_to_c(closure) in {one.link_id for one in fallen}
    assert a_to_c(closure) not in {one.link_id for one in standing}


def test_two_derived_links_supporting_each_other_do_not_stand_on_nothing() -> None:
    # part_of a->b derives has_part b->a, which derives part_of a->b again. Withdrawing
    # the assertion must take both down rather than leaving the circle standing.
    closure = close([PART_AB], SCHEMA)
    # The domain and range type both ends too; those stand or fall with the link.
    derived = {*(one.id for one in closure.links), *(one.fact for one in closure.typings)}

    assert supported(closure, ()) == {"ab", *derived}
    assert supported(closure, {"ab"}) == set()


def test_the_package_marks_which_relations_nobody_claimed() -> None:
    store = store_with(PART_AB, PART_BC)
    derived = entail({"store": store, "schema": SCHEMA}, EntailOptions())["derived"]
    hits = (Hit(node=store.get_node("a" * 16), score=0.5),)

    bundle = graph_expand_entailed(
        {"store": store, "hits": hits, "derived": derived, "schema": SCHEMA},
        GraphExpandOptions(depth=2, limit=20),
    )["bundle"]

    assert bundle.derived
    assert set(bundle.derived) <= {one.id for one in bundle.links}
    assert bundle.method == "graph_expand_entailed"
