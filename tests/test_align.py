"""Tests for putting a procedure beside a run of it and naming every departure.

The four kinds are each tested, and so are the two properties that make the report
worth reading: a step carried out under another name is reported as `renamed` rather
than quietly matched, and a correspondence somebody has already asserted is believed
over the shallow matcher, which is what makes a wrong match fixable in the data.
"""

from __future__ import annotations

from atlas.model import Agent, Assertion, Link, Node, Schema, Segment, Source, Span
from atlas.ontology import load
from atlas.steps.align import AlignOptions, align
from atlas.store.memory import MemoryStore

OPTIONS = AlignOptions(plan="ProtocolStep", run="ExecutionStep", asserted=("realises",))
TEXT = "wash the sample\ndry the sample\nweigh the sample\nrinse the sample\nlog the reading\n"


def store_with(planned: list[tuple[str, int]], actual: list[tuple[str, int]],
               matched: list[tuple[str, str]] | None = None) -> tuple[MemoryStore, Schema, dict]:
    """A store holding two step lists, each step bound to the line that names it."""
    schema = load("science_core", "process")
    lines = TEXT.splitlines(keepends=True)
    source = Source(id="protocol", origin="protocol.txt",
                    segments=tuple(Segment(number=n, text=line)
                                   for n, line in enumerate(lines, start=1)))
    nodes: dict[str, Node] = {}
    for kind, steps in (("ProtocolStep", planned), ("ExecutionStep", actual)):
        for label, order in steps:
            segment = next(n for n, line in enumerate(lines, start=1) if label in line)
            text = source.segment_text(segment)
            start = text.index(label)
            nodes[f"{kind[0].lower()}:{label}:{order}"] = Node(
                id=f"{kind[:1]}{order}{abs(hash(label)) % 10**8:08d}",
                type=kind,
                fields={"name": label, "order": str(order)},
                spans=(Span.of(source, segment, start, start + len(label)),),
                schema_version=schema.version,
            )
    store = MemoryStore()
    store.add_source(source)
    agent = Agent(id="fixture", kind="run")
    targets: list[Node | Link] = list(nodes.values())
    for src, dst in matched or []:
        text = source.segment_text(1)
        targets.append(Link.of(predicate="realises", src=nodes[src].id, dst=nodes[dst].id,
                               spans=(Span.of(source, 1, 0, len(text.rstrip())),),
                               schema_version=schema.version))
    for index, target in enumerate(targets):
        store.assert_(Assertion(id=f"a{index:03d}", agent=agent, at="2026-01-01T00:00:00+00:00",
                                target=target))
    return store, schema, nodes


def run(planned, actual, matched=None, options: AlignOptions = OPTIONS):
    store, schema, nodes = store_with(planned, actual, matched)
    return align({"store": store, "schema": schema}, options), nodes


def test_two_lists_that_agree_have_no_departures() -> None:
    result, _nodes = run([("wash", 1), ("dry", 2)], [("wash", 1), ("dry", 2)])

    assert result["discrepancies"] == ()
    assert len(result["alignment"]) == 2


def test_a_planned_step_that_did_not_happen_is_missing() -> None:
    result, _nodes = run([("wash", 1), ("dry", 2)], [("wash", 1)])

    [found] = result["discrepancies"]
    assert found.kind == "missing"
    assert found.planned is not None and found.planned.label == "dry"


def test_a_step_that_happened_and_was_not_planned_is_extra() -> None:
    result, _nodes = run([("wash", 1)], [("wash", 1), ("rinse", 2)])

    [found] = result["discrepancies"]
    assert found.kind == "extra"
    assert found.actual is not None and found.actual.label == "rinse"


def test_steps_carried_out_in_the_wrong_order_are_reported() -> None:
    result, _nodes = run([("wash", 1), ("dry", 2)], [("dry", 1), ("wash", 2)])

    kinds = {found.kind for found in result["discrepancies"]}
    assert "reordered" in kinds


def test_a_step_carried_out_under_another_name_is_reported_not_swallowed() -> None:
    # Two labels sharing a word: the shallow matcher pairs them, and says so.
    result, _nodes = run([("wash the sample", 1)], [("rinse the sample", 1)])

    renamed = [found for found in result["discrepancies"] if found.kind == "renamed"]
    assert renamed
    assert "wash the sample" in renamed[0].detail and "rinse the sample" in renamed[0].detail
    assert len(result["alignment"]) == 1


def test_labels_sharing_nothing_are_not_matched_at_all() -> None:
    result, _nodes = run([("wash", 1)], [("log", 1)])

    assert {found.kind for found in result["discrepancies"]} == {"missing", "extra"}
    assert result["alignment"] == ()


def test_an_asserted_correspondence_is_believed_over_the_shallow_matcher() -> None:
    result, _nodes = run(
        [("wash", 1)], [("log", 1)],
        matched=[("e:log:1", "p:wash:1")],
    )

    assert len(result["alignment"]) == 1
    # Believed, and therefore not reported as a rename: somebody already decided this.
    assert result["discrepancies"] == ()
