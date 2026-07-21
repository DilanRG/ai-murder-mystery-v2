"""
tests/conftest.py — Shared fixtures for the AI Murder Mystery v2 test suite.
"""
import pytest
from game.content import load_case, load_location
from game.story_director import fallback_story_presentation
from world.state import WorldState, CharacterState, ClueState, GamePhase
from story.models import LocationDef, Scenario, MurderDetails, CharacterDef


def make_dummy_generated_document() -> dict[str, object]:
    """Return provider-shaped canonical output without making a provider call."""

    case = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    case_data = case.model_dump(mode="json")
    retained_evidence_ids = {
        "ev_library_poker",
        "ev_fireplace_trace",
        "ev_medical_assessment",
        "ev_library_clock",
        "ev_edgar_cuff_fibre",
        "ev_vivienne_memo",
        "ev_sabrina_earring",
        "ev_captain_letter",
        "ev_port_rag",
        "ev_sabrina_captain_alibi",
    }
    case_data["evidence"] = {
        evidence_id: evidence
        for evidence_id, evidence in case_data["evidence"].items()
        if evidence_id in retained_evidence_ids
    }
    for fact in case_data["facts"].values():
        fact["related_evidence_ids"] = [
            evidence_id
            for evidence_id in fact["related_evidence_ids"]
            if evidence_id in retained_evidence_ids
        ]
    for overlay in case_data["overlays"].values():
        overlay["supporting_evidence_ids"] = [
            evidence_id
            for evidence_id in overlay["supporting_evidence_ids"]
            if evidence_id in retained_evidence_ids
        ]
    case_data["solution"]["method_evidence_ids"] = [
        "ev_library_poker",
        "ev_fireplace_trace",
        "ev_medical_assessment",
    ]
    case_data["solution"]["motive_evidence_ids"] = ["ev_vivienne_memo"]
    case_data["solution"]["opportunity_evidence_ids"] = [
        "ev_library_clock",
        "ev_edgar_cuff_fibre",
    ]
    opening = dict(case_data["opening"])
    opening.pop("assembly_room_id")
    presentation = fallback_story_presentation(case, location).model_dump(mode="json")
    for host_field in ("schema_version", "base_case_fingerprint", "source"):
        presentation.pop(host_field)
    return {
        "schema_version": 1,
        "case": {
            "schema_version": 1,
            "title": case.title,
            "investigation_start_minute": case.investigation_start_minute,
            "murder": case_data["murder"],
            "facts": case_data["facts"],
            "timeline": case_data["timeline"],
            "overlays": case_data["overlays"],
            "evidence": case_data["evidence"],
            "opening": opening,
            "solution": case_data["solution"],
        },
        "presentation": presentation,
    }


def make_location(id: str, name: str, connected_to: list[str] | None = None) -> LocationDef:
    return LocationDef(
        id=id,
        name=name,
        description=f"The {name}.",
        connected_to=connected_to or [],
        objects=[],
    )


def make_world(num_locations: int = 2) -> WorldState:
    """Return a minimal WorldState for testing."""
    locs = {
        "hall":   make_location("hall",    "Hall",    ["library"]),
        "library": make_location("library", "Library", ["hall"]),
    }
    chars = {
        "Alice": CharacterState(name="Alice", location_id="hall",    alive=True, role="killer"),
        "Bob":   CharacterState(name="Bob",   location_id="library", alive=True, role="suspect"),
        "Detective": CharacterState(name="Detective", location_id="hall", alive=True, role="detective"),
    }
    clues = {
        "clue1": ClueState(
            id="clue1", description="A torn glove",
            location_id="hall", points_to="Alice",
            difficulty="easy", clue_type="physical",
        ),
        "clue2": ClueState(
            id="clue2", description="A suspicious note",
            location_id="library", points_to="Alice",
            difficulty="hard", clue_type="paper",
        ),
    }
    return WorldState(locations=locs, characters=chars, clues=clues, player_name="Detective")
