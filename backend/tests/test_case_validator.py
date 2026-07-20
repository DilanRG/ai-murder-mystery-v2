"""Focused cross-reference and solvability checks for the content validator."""

from __future__ import annotations

from game.content import load_case, load_location
from game.models import CaseDefinition, LocationPackage
from game.validator import validate_case, validate_location_package


def _case_copy() -> dict:
    return load_case("ashwick_sample").model_dump(mode="json")


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def test_authored_sample_case_and_location_pass_cross_validation() -> None:
    report = validate_case(load_case("ashwick_sample"), load_location("ashwick_manor"))
    assert report.is_valid, report.issues


def test_location_validator_accumulates_bad_reference_and_disconnected_map() -> None:
    data = load_location("ashwick_manor").model_dump(mode="json")
    data["rooms"]["library"]["searchable_object_ids"].append("missing_object")
    data["doors"] = []
    report = validate_location_package(LocationPackage.model_validate(data))
    assert {"unknown_object", "disconnected_map"} <= _codes(report)


def test_case_validator_catches_roles_schedule_and_murder_opportunity() -> None:
    data = _case_copy()
    data["overlays"]["edgar_blackwood"]["role"] = "innocent"
    data["overlays"]["edgar_blackwood"]["schedule"][1]["end_minute"] = 1313
    data["murder"]["method"] = "stabbing"
    report = validate_case(CaseDefinition.model_validate(data), load_location("ashwick_manor"))
    assert {"invalid_role_counts", "murderer_role_mismatch", "overlapping_schedule", "method_weapon_mismatch", "invalid_murder_opportunity"} <= _codes(report)


def test_case_validator_catches_observation_fact_and_solution_resilience() -> None:
    data = _case_copy()
    data["overlays"]["zara_okonkwo"]["observations"][0]["minute"] = 1
    data["overlays"]["zara_okonkwo"]["observations"][0]["room_id"] = "chapel"
    data["evidence"]["ev_library_poker"]["fact_ids"] = ["fact_missing"]
    data["evidence"]["ev_library_poker"]["manipulable"] = True
    data["solution"]["method_evidence_ids"] = ["ev_library_poker"]
    data["solution"]["motive_evidence_ids"] = ["ev_vivienne_memo"]
    data["solution"]["opportunity_evidence_ids"] = ["ev_library_clock"]
    report = validate_case(CaseDefinition.model_validate(data), load_location("ashwick_manor"))
    assert {"implausible_observation", "unknown_fact", "manipulable_clue_breaks_solution"} <= _codes(report)
