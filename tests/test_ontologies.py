"""Every ontology the library ships: it loads, it is inside the profiles it declares, and it
is consistent with every class able to have members.

These are the standing checks on the shipped ontologies themselves. An ontology module that
drifted out of its profile would be refused by the first architecture that named it; one
with an empty class would produce impossible nodes; and one that did not load would break
every manifest that names it. All three are cheaper to find here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph, URIRef

from atlas.ontology import SHIPPED, load
from atlas.ontology.vocabulary import ATLAS, OWL, RDF
from atlas.reason.profile import outside
from atlas.reason.tableau import decide

ROOT = next(one for one in SHIPPED if one.is_dir())
MODULES = sorted(path.stem for path in ROOT.glob("*.ttl") if path.stem != "atlas")
SHAPES = sorted(path.stem for path in (ROOT / "shapes").glob("*.ttl"))


def declared(name: str) -> list[str]:
    graph = Graph()
    graph.parse(ROOT / f"{name}.ttl", format="turtle")
    ontology = next(s for s in graph.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef))
    return sorted(str(one) for one in graph.objects(ontology, ATLAS.profile))


def test_every_module_declares_the_profiles_it_is_written_for() -> None:
    assert MODULES
    assert all(declared(name) for name in MODULES)


@pytest.mark.parametrize("name", MODULES)
def test_a_module_with_its_imports_is_inside_every_profile_it_declares(name: str) -> None:
    schema = load(name)
    for profile in declared(name):
        assert outside(schema.every_axiom(), profile) == [], (name, profile)


@pytest.mark.parametrize("name", MODULES)
def test_a_module_is_consistent_and_every_class_can_have_members(name: str) -> None:
    schema = load(name)
    verdict = decide(schema.every_axiom(), [one.name for one in schema.types])
    assert verdict.consistent and verdict.decided, (name, verdict)
    assert verdict.unsatisfiable == () and schema.unsatisfiable == ()
    assert schema.unread == () and schema.imports == ()


@pytest.mark.parametrize("name", SHAPES)
def test_every_shapes_file_parses(name: str) -> None:
    assert len(Graph().parse(ROOT / "shapes" / f"{name}.ttl", format="turtle")) > 0


def test_no_term_of_the_substrate_is_part_of_any_vocabulary() -> None:
    schema = load(Path(ROOT / "atlas.ttl"))
    assert schema.types == () and schema.predicates == ()
