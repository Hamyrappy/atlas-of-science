"""Tests for executing a mapping over rows, and for the join that must never happen.

The rule the module turns on is that an empty key never joins. A row missing the column
that identifies a thing produces no node and therefore no relation -- because letting it
through as the empty string collapses every such row into one node and makes every
relation touching it a claim about a thing that does not exist. That is the first test,
and it is the one worth keeping if the rest are ever rewritten.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.ontology import load
from atlas.steps.ingest_table import read_table
from atlas.steps.map_rows import LinkMapping, MapRowsOptions, NodeMapping, identity, map_rows

ROWS = (
    "study,study_name,result,outcome,value,unit\n"
    "S-1,First series,R-1,yield rose,0.94,fraction\n"
    "S-1,First series,R-2,yield rose again,0.95,fraction\n"
    "S-2,Second series,R-3,no change,0.02,fraction\n"
)

MAPPING = MapRowsOptions(
    nodes={
        "study": NodeMapping(type="Study", key="study", fields={"name": "study_name"}),
        "result": NodeMapping(type="StudyResult", key="result", span="outcome",
                              fields={"statement": "outcome", "value": "value",
                                      "unit": "unit"}),
    },
    links=(LinkMapping(predicate="produced_by", src="result", dst="study", span="study"),),
)


@pytest.fixture
def state(tmp_path: Path):
    def build(rows: str = ROWS) -> dict:
        path = tmp_path / "results.csv"
        path.write_text(rows, encoding="utf-8")
        return {"sources": (read_table(path),), "schema": load("science_core")}
    return build


def test_a_mapping_produces_typed_nodes_bound_to_the_rows_they_came_from(state) -> None:
    result = map_rows(state(), MAPPING)

    results = [one for one in result["nodes"] if one.type == "StudyResult"]
    assert len(results) == 3
    assert results[0].fields == {"statement": "yield rose", "value": "0.94",
                                 "unit": "fraction"}
    assert results[0].spans[0].text == "yield rose"


def test_a_thing_named_in_two_rows_is_one_node(state) -> None:
    result = map_rows(state(), MAPPING)

    studies = [one for one in result["nodes"] if one.type == "Study"]
    assert len(studies) == 2
    assert studies[0].id == identity("Study", "S-1")


def test_a_node_is_minted_from_the_first_row_that_identifies_it(state) -> None:
    result = map_rows(state(), MAPPING)

    study = next(one for one in result["nodes"] if one.id == identity("Study", "S-1"))
    assert study.spans[0].segment == 1


def test_a_relation_between_two_things_of_one_row_is_made(state) -> None:
    result = map_rows(state(), MAPPING)

    assert len(result["links"]) == 3
    assert {one.predicate for one in result["links"]} == {"produced_by"}
    assert result["mapping_violations"] == ()


def test_an_empty_key_never_joins(state) -> None:
    rows = (
        "study,study_name,result,outcome,value,unit\n"
        ",First series,R-1,yield rose,0.94,fraction\n"
        ",Second series,R-3,no change,0.02,fraction\n"
    )

    result = map_rows(state(rows), MAPPING)

    # Two rows with no study: no study node, and therefore no relation claiming that
    # both results came out of one investigation.
    assert [one.type for one in result["nodes"]] == ["StudyResult", "StudyResult"]
    assert result["links"] == ()
    assert result["unmapped"] == 2


def test_a_relation_the_pack_forbids_is_reported_rather_than_made(state) -> None:
    wrong = MAPPING.model_copy(update={
        "links": (LinkMapping(predicate="produced_by", src="study", dst="result",
                              span="study"),),
    })

    result = map_rows(state(), wrong)

    assert result["links"] == ()
    assert "expects domain 'StudyResult'" in result["mapping_violations"][0]


def test_a_field_the_row_leaves_blank_contributes_nothing(state) -> None:
    rows = (
        "study,study_name,result,outcome,value,unit\n"
        "S-1,First series,R-1,yield rose,,fraction\n"
    )

    result = map_rows(state(rows), MAPPING)

    [one] = [node for node in result["nodes"] if node.type == "StudyResult"]
    assert "value" not in one.fields


def test_an_identity_is_stable_across_runs_and_files() -> None:
    assert identity("Study", "S-1") == identity("Study", "S-1")
    assert identity("Study", "S-1") != identity("StudyResult", "S-1")


def test_a_relation_with_no_column_named_stands_on_the_whole_row(state) -> None:
    whole = MAPPING.model_copy(update={
        "links": (LinkMapping(predicate="produced_by", src="result", dst="study"),),
    })

    result = map_rows(state(), whole)

    assert result["links"][0].spans[0].text.startswith("study: S-1")
