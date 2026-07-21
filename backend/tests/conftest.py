"""
tests/conftest.py — Shared fixtures for the AI Murder Mystery Game test suite.
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
        "ev_edgar_cuff_fibre",
        "ev_inspector_arrival",
        "ev_vivienne_memo",
        "ev_trust_draft",
        "ev_captain_letter",
        "ev_sabrina_earring",
        "ev_port_rag",
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
        observed_fact_ids = {
            fact_id
            for observation in overlay["observations"]
            for fact_id in observation["fact_ids"]
        }
        overlay["hides_fact_ids"] = [
            fact_id
            for fact_id in overlay["hides_fact_ids"]
            if fact_id in observed_fact_ids
        ]
        overlay["alibi_disclosed_fact_ids"] = [
            fact_id
            for fact_id in overlay["alibi_disclosed_fact_ids"]
            if fact_id in observed_fact_ids
        ]
        for lie in overlay["lies"]:
            lie["disclosed_fact_ids"] = [
                fact_id
                for fact_id in lie["disclosed_fact_ids"]
                if fact_id in observed_fact_ids
            ]
        overlay["supporting_evidence_ids"] = [
            evidence_id
            for evidence_id in overlay["supporting_evidence_ids"]
            if evidence_id in retained_evidence_ids
            and observed_fact_ids
            & set(case_data["evidence"][evidence_id]["fact_ids"])
        ]
    for evidence in case_data["evidence"].values():
        implicated = set(evidence["implicates_character_ids"])
        evidence["exonerates_character_ids"] = [
            character_id
            for character_id in evidence["exonerates_character_ids"]
            if character_id not in implicated
        ]
    murder = case_data["murder"]
    opening_data = case_data["opening"]
    for event in case_data["timeline"]:
        def participant_is_present(character_id: str) -> bool:
            schedule = case_data["overlays"][character_id]["schedule"]
            scheduled = any(
                entry["start_minute"] <= event["minute"] < entry["end_minute"]
                and entry["room_id"] == event["room_id"]
                for entry in schedule
            )
            transition = event["event_type"] in {"schedule", "observation"} and any(
                entry["end_minute"] == event["minute"]
                and entry["room_id"] == event["room_id"]
                for entry in schedule
            )
            body = (
                character_id == murder["victim_id"]
                and event["minute"] >= murder["minute"]
                and event["room_id"] == murder["room_id"]
            )
            assembly = (
                character_id != murder["victim_id"]
                and event["event_type"] == "meeting"
                and event["minute"] >= opening_data["discovery_minute"]
                and event["room_id"] == opening_data["assembly_room_id"]
            )
            return scheduled or transition or body or assembly

        event["actor_ids"] = [
            character_id
            for character_id in event["actor_ids"]
            if participant_is_present(character_id)
        ]
        event["observed_by"] = [
            character_id
            for character_id in event["observed_by"]
            if participant_is_present(character_id)
        ]
    for character_id, overlay in case_data["overlays"].items():
        for observation in overlay["observations"]:
            scheduled = any(
                entry["start_minute"]
                <= observation["minute"]
                < entry["end_minute"]
                and entry["room_id"] == observation["room_id"]
                for entry in overlay["schedule"]
            )
            event_supported = any(
                event["minute"] == observation["minute"]
                and event["room_id"] == observation["room_id"]
                and character_id in (*event["actor_ids"], *event["observed_by"])
                for event in case_data["timeline"]
            )
            private_fact = any(
                case_data["facts"][fact_id]["category"] == "secret"
                and character_id
                in case_data["facts"][fact_id]["related_character_ids"]
                for fact_id in observation["fact_ids"]
            )
            if not (scheduled or event_supported or private_fact):
                first_schedule = overlay["schedule"][0]
                observation["minute"] = first_schedule["start_minute"]
                observation["room_id"] = first_schedule["room_id"]
    # The generated admission fixture deliberately has two complete proof
    # paths, unlike the authored spine it is projected from.
    case_data["evidence"]["ev_fireplace_trace"]["redundancy_group"] = "means_trace"
    case_data["evidence"]["ev_trust_draft"]["redundancy_group"] = "motive_trust"
    case_data["evidence"]["ev_inspector_arrival"]["redundancy_group"] = "timeline_arrival"
    case_data["solution"]["method_evidence_ids"] = ["ev_medical_assessment", "ev_fireplace_trace"]
    case_data["solution"]["motive_evidence_ids"] = ["ev_vivienne_memo", "ev_trust_draft"]
    case_data["solution"]["opportunity_evidence_ids"] = [
        "ev_edgar_cuff_fibre",
        "ev_inspector_arrival",
    ]
    case_data["solution"]["timeline_fact_ids"] = [
        "fact_murder_time",
        "fact_edgar_hall_arrival",
    ]
    generated_solution = {
        **case_data["solution"],
        "evidence_routes": [
            {
                "id": "authored_projection_route_a",
                "label": "Medical finding, memo, and cuff-fibre route",
                "method_evidence_ids": ["ev_medical_assessment"],
                "motive_evidence_ids": ["ev_vivienne_memo"],
                "opportunity_evidence_ids": ["ev_edgar_cuff_fibre"],
                "timeline_fact_ids": ["fact_murder_time"],
            },
            {
                "id": "authored_projection_route_b",
                "label": "Fireplace trace, trust draft, and arrival route",
                "method_evidence_ids": ["ev_fireplace_trace"],
                "motive_evidence_ids": ["ev_trust_draft"],
                "opportunity_evidence_ids": ["ev_inspector_arrival"],
                "timeline_fact_ids": ["fact_edgar_hall_arrival"],
            },
        ],
    }
    opening = dict(case_data["opening"])
    for host_owned_field in (
        "assembly_room_id",
        "body_condition",
        "discoverer_observations",
        "containment_statement",
        "initial_reactions",
    ):
        opening.pop(host_owned_field)
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
            "solution": generated_solution,
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
