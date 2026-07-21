"""Admission checks for independently complete generated proof routes."""

from __future__ import annotations

from copy import deepcopy

import pytest
from conftest import make_dummy_generated_document

from game.case_generation import (
    GeneratedScenarioDocument,
    GeneratedScenarioError,
    compile_generated_scenario,
)
from game.content import load_case, load_location


def _compile(document: dict[str, object]) -> None:
    source = load_case("ashwick_sample")
    compile_generated_scenario(
        document,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=812,
    )


def test_generated_case_requires_two_complete_disjoint_proof_routes() -> None:
    document = make_dummy_generated_document()
    routes = document["case"]["solution"]["evidence_routes"]  # type: ignore[index]
    document["case"]["solution"]["evidence_routes"] = [routes[0]]  # type: ignore[index]

    with pytest.raises(GeneratedScenarioError, match="invalid generated case schema"):
        _compile(document)
    route_schema = GeneratedScenarioDocument.model_json_schema()["$defs"][
        "GeneratedSolutionRequirements"
    ]["properties"]["evidence_routes"]
    assert route_schema["minItems"] == 2


@pytest.mark.parametrize("overlap", ("evidence", "prerequisite", "redundancy_group"))
def test_generated_routes_do_not_count_shared_evidence_prerequisites_or_groups_as_independent(
    overlap: str,
) -> None:
    document = make_dummy_generated_document()
    mutated = deepcopy(document)
    routes = mutated["case"]["solution"]["evidence_routes"]  # type: ignore[index]
    if overlap == "evidence":
        routes[1]["method_evidence_ids"] = ["ev_medical_assessment"]
    elif overlap == "prerequisite":
        mutated["case"]["evidence"]["ev_fireplace_trace"]["prerequisite_evidence_ids"] = ["ev_medical_assessment"]  # type: ignore[index]
    else:
        evidence = mutated["case"]["evidence"]  # type: ignore[index]
        evidence["ev_fireplace_trace"]["redundancy_group"] = "means_forensics"

    with pytest.raises(GeneratedScenarioError, match="overlapping_independent_evidence_routes"):
        _compile(mutated)


def test_each_generated_route_must_independently_support_the_culprit_and_timeline() -> None:
    document = make_dummy_generated_document()
    route = document["case"]["solution"]["evidence_routes"][1]  # type: ignore[index]
    route["timeline_fact_ids"] = ["fact_edgar_library_presence"]
    document["case"]["evidence"]["ev_fireplace_trace"]["implicates_character_ids"] = []  # type: ignore[index]
    document["case"]["evidence"]["ev_trust_draft"]["implicates_character_ids"] = []  # type: ignore[index]
    document["case"]["evidence"]["ev_inspector_arrival"]["implicates_character_ids"] = []  # type: ignore[index]

    with pytest.raises(GeneratedScenarioError, match="route_culprit_not_uniquely_supported"):
        _compile(document)


def test_each_generated_route_must_carry_its_own_timeline_support() -> None:
    document = make_dummy_generated_document()
    route = document["case"]["solution"]["evidence_routes"][0]  # type: ignore[index]
    route["timeline_fact_ids"] = ["fact_edgar_hall_arrival"]

    with pytest.raises(GeneratedScenarioError, match="route_timeline_not_supported"):
        _compile(document)
