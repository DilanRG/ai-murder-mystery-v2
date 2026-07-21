"""
tests/conftest.py — Shared fixtures for the AI Murder Mystery v2 test suite.
"""
import pytest
from game.content import load_case, load_location
from game.models import CaseDefinition
from game.story_director import fallback_story_presentation
from world.state import WorldState, CharacterState, ClueState, GamePhase
from story.models import LocationDef, Scenario, MurderDetails, CharacterDef


def _remap_generated_case_value(value: object, character_ids: dict[str, str]) -> object:
    """Apply the recipe materializer's ID/route projection to fixture JSON."""

    if isinstance(value, dict):
        return {
            character_ids.get(key, key): _remap_generated_case_value(item, character_ids)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_remap_generated_case_value(item, character_ids) for item in value]
    if not isinstance(value, str):
        return value
    if value in character_ids:
        return character_ids[value]
    if ":" in value:
        route, target = value.split(":", 1)
        if target in character_ids:
            return f"{route}:{character_ids[target]}"
    return value


def make_dummy_generated_document(
    *,
    character_ids: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Return provider-shaped truth projected onto an exact eight-card cast.

    This is deliberately a test fixture, not an alternate generation path.  It
    starts with the authored sample spine and applies the same ID/route mapping
    shape used by recipe materialization, allowing normal ``/game/new`` tests
    to exercise arbitrary automatic casts without OpenRouter.
    """

    case = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    case_data = case.model_dump(mode="json")
    if character_ids is not None:
        if len(character_ids) != 8 or len(set(character_ids)) != 8:
            raise ValueError("dummy generated casts must contain exactly eight unique IDs")
        character_map = dict(zip(case.character_ids, character_ids, strict=True))
        case_data = _remap_generated_case_value(case_data, character_map)
        assert isinstance(case_data, dict)
        case = CaseDefinition.model_validate(case_data)
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
