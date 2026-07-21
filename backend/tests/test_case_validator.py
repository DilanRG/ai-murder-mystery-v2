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


def test_case_validator_rejects_generated_case_discovery_dead_ends() -> None:
    data = _case_copy()
    data["evidence"]["ev_vivienne_memo"]["discoverable_via"] = []
    data["evidence"]["ev_fireplace_trace"]["prerequisite_evidence_ids"] = [
        "ev_library_poker"
    ]
    data["evidence"]["ev_library_poker"]["prerequisite_evidence_ids"] = [
        "ev_fireplace_trace"
    ]
    data["evidence"]["ev_edgar_cuff_fibre"]["discoverable_via"] = [
        "search:study_desk"
    ]
    data["solution"]["method_evidence_ids"] = ["ev_vivienne_memo"]
    data["evidence"]["ev_vivienne_memo"]["prerequisite_evidence_ids"] = [
        "ev_sabrina_earring"
    ]
    data["evidence"]["ev_sabrina_earring"]["discoverable_via"] = []
    data["evidence"]["ev_captain_letter"]["discoverable_via"] = [
        "interview:lady_vivienne_ashford"
    ]
    data["evidence"]["ev_port_rag"]["discoverable_via"] = [
        "examine:edgar_blackwood"
    ]
    data["overlays"]["dr_celestine_moreau"]["schedule"] = [
        entry
        for entry in data["overlays"]["dr_celestine_moreau"]["schedule"]
        if not (
            entry["start_minute"]
            <= data["opening"]["discovery_minute"]
            < entry["end_minute"]
        )
    ]

    report = validate_case(
        CaseDefinition.model_validate(data), load_location("ashwick_manor")
    )

    assert {
        "undiscoverable_solution_evidence",
        "cyclic_evidence_prerequisite",
        "slot_discovery_route_mismatch",
        "solution_evidence_axis_mismatch",
        "infeasible_discoverer_schedule",
        "undiscoverable_solution_prerequisite",
        "invalid_discovery_route",
    } <= _codes(report)


def test_case_validator_rejects_unscorable_or_incomplete_solution_axes() -> None:
    data = _case_copy()
    data["solution"]["method_evidence_ids"] = []
    data["solution"]["timeline_fact_ids"] = ["fact_financial_exposure"]
    data["facts"]["fact_financial_exposure"]["related_evidence_ids"].remove(
        "ev_vivienne_memo"
    )
    data["facts"]["fact_vivienne_intent"]["related_evidence_ids"].remove(
        "ev_vivienne_memo"
    )

    report = validate_case(
        CaseDefinition.model_validate(data), load_location("ashwick_manor")
    )

    assert {
        "missing_solution_axis",
        "invalid_solution_timeline_fact",
        "nonreciprocal_solution_link",
    } <= _codes(report)


def test_case_validator_rejects_impossible_murder_discovery_chronology() -> None:
    data = _case_copy()
    murder_minute = data["murder"]["minute"]
    data["opening"]["discovery_minute"] = murder_minute - 1
    data["investigation_start_minute"] = murder_minute - 2

    report = validate_case(
        CaseDefinition.model_validate(data), load_location("ashwick_manor")
    )

    assert {
        "invalid_murder_discovery_order",
        "invalid_discovery_investigation_order",
    } <= _codes(report)
