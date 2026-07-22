"""
tests/conftest.py — Shared fixtures for the AI Murder Mystery Game test suite.
"""
from copy import deepcopy

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


def generated_stage_payloads(
    document: dict[str, object],
) -> dict[str, dict[str, object]]:
    """Project one valid fixture across the Revision 10 immutable stage seams."""

    case = document["case"]
    assert isinstance(case, dict)
    facts = case["facts"]
    timeline = deepcopy(case["timeline"])
    evidence = case["evidence"]
    solution = case["solution"]
    assert isinstance(facts, dict)
    assert isinstance(timeline, list)
    assert isinstance(evidence, dict)
    assert isinstance(solution, dict)
    routes = solution["evidence_routes"]
    assert isinstance(routes, list)
    location = load_location("ashwick_manor")
    timeline_fact_ids = {
        fact_id for event in timeline for fact_id in event["fact_ids"]
    }
    synthetic_index = 0
    for source in evidence.values():
        if not source["is_red_herring"]:
            continue
        missing = [
            fact_id for fact_id in source["fact_ids"] if fact_id not in timeline_fact_ids
        ]
        if not missing:
            continue
        synthetic_index += 1
        slot = location.evidence_slots[source["initial_slot_id"]]
        related_actor_ids = list(
            dict.fromkeys(
                character_id
                for fact_id in missing
                for character_id in facts[fact_id]["related_character_ids"]
            )
        )
        scheduled_source = next(
            (
                (character_id, entry)
                for character_id in related_actor_ids
                for entry in case["overlays"][character_id]["schedule"]
                if entry["room_id"] == slot.room_id
            ),
            None,
        )
        if scheduled_source is None:
            scheduled_source = next(
                (
                    (character_id, entry)
                    for character_id in related_actor_ids
                    for entry in case["overlays"][character_id]["schedule"]
                ),
                None,
            )
        assert scheduled_source is not None
        source_actor_id, source_schedule = scheduled_source
        timeline.append(
            {
                "id": f"timeline_fixture_misdirection_{synthetic_index}",
                "minute": source_schedule["start_minute"],
                "event_type": "observation",
                "room_id": source_schedule["room_id"],
                "actor_ids": [source_actor_id],
                "summary": "A non-murder secret left a misleading but explainable trace.",
                "fact_ids": missing,
                "observed_by": [],
            }
        )
        timeline_fact_ids.update(missing)
    timeline.sort(key=lambda event: (event["minute"], event["id"]))
    for event in timeline:
        if event["id"] == "timeline_vivienne_arrives_library":
            event["fact_ids"] = list(
                dict.fromkeys([*event["fact_ids"], "fact_financial_exposure"])
            )

    def event_for(fact_ids: list[str]) -> dict[str, object]:
        for event in timeline:
            if set(fact_ids) <= set(event["fact_ids"]):
                return event
        raise AssertionError(f"fixture lacks one source event for {fact_ids!r}")

    def event_for_or_attach(fact_ids: list[str]) -> dict[str, object]:
        try:
            return event_for(fact_ids)
        except AssertionError:
            source = next(
                event
                for event in timeline
                if set(fact_ids) & set(event["fact_ids"])
            )
            source["fact_ids"] = list(
                dict.fromkeys([*source["fact_ids"], *fact_ids])
            )
            return source

    proof_routes: list[dict[str, object]] = []
    realizations: dict[str, dict[str, object]] = {}
    used_axis_channels: dict[str, set[tuple[object, ...]]] = {
        "method": set(),
        "motive": set(),
        "opportunity": set(),
    }
    synthetic_proof_index = 0

    def channel_for(source: dict[str, object], event: dict[str, object]) -> tuple[object, ...]:
        return (
            source["kind"],
            event["minute"],
            event["room_id"],
            tuple(sorted([*event["actor_ids"], *event["observed_by"]])),
            event["event_type"],
        )

    def independent_source_event(
        axis: str,
        source: dict[str, object],
        claim_fact_ids: list[str],
    ) -> dict[str, object]:
        nonlocal synthetic_proof_index
        base = event_for_or_attach(claim_fact_ids)
        channel = channel_for(source, base)
        if channel not in used_axis_channels[axis]:
            used_axis_channels[axis].add(channel)
            return base
        synthetic_proof_index += 1
        minute = min(
            case["investigation_start_minute"] - 1,
            base["minute"] + synthetic_proof_index,
        )
        if minute == base["minute"]:
            minute = max(0, base["minute"] - synthetic_proof_index)
        alternate = {
            "id": f"timeline_fixture_proof_origin_{synthetic_proof_index}",
            "minute": minute,
            "event_type": "observation",
            "room_id": base["room_id"],
            "actor_ids": list(base["actor_ids"]),
            "summary": (
                "A separate canonical object interaction creates an independent "
                f"{axis} evidence channel."
            ),
            "fact_ids": list(claim_fact_ids),
            "observed_by": list(base["observed_by"]),
        }
        timeline.append(alternate)
        used_axis_channels[axis].add(channel_for(source, alternate))
        return alternate

    for route_index, route in enumerate(routes[:2], start=1):
        route_id = f"route_{route_index}"
        claims: dict[str, dict[str, object]] = {}
        for axis, category_names, pick_last in (
            ("method", {"means"}, False),
            ("motive", {"motive"}, True),
            ("opportunity", {"opportunity", "timeline"}, False),
        ):
            evidence_id = route[f"{axis}_evidence_ids"][0]
            source = evidence[evidence_id]
            candidates = [
                fact_id
                for fact_id in source["fact_ids"]
                if facts[fact_id]["category"] in category_names
            ]
            if axis == "opportunity":
                candidates = list(dict.fromkeys([*candidates, *route["timeline_fact_ids"]]))
                claim_fact_ids = candidates
            else:
                claim_fact_ids = candidates if pick_last else [candidates[0]]
            source_event = independent_source_event(axis, source, claim_fact_ids)
            claim = {
                "claim": f"Route {route_index} {axis} claim grounded in accepted facts.",
                "fact_ids": claim_fact_ids,
                "source_event_ids": [source_event["id"]],
                "evidence_role_summary": f"Concrete {source['kind']} support for {axis}.",
                "required_form": source["kind"],
            }
            claims[axis] = claim
            if source["initial_slot_id"]:
                discovery = {"kind": "slot", "target_id": source["initial_slot_id"]}
            elif "examine:body" in source["discoverable_via"]:
                discovery = {"kind": "body", "target_id": "body"}
            else:
                interview_routes = [
                    value.split(":", 1)[1]
                    for value in source["discoverable_via"]
                    if value.startswith("interview:")
                ]
                discovery = (
                    {"kind": "interview", "target_id": interview_routes[0]}
                    if interview_routes
                    else {"kind": "body", "target_id": "body"}
                )
            role_id = f"{route_id}_{axis}"
            realizations[role_id] = {
                "role_id": role_id,
                "route_id": route_id,
                "axis": axis,
                "name": source["name"],
                "description": source["description"],
                "kind": source["kind"],
                "supported_fact_ids": claim_fact_ids,
                "source_event_id": source_event["id"],
                "causal_origin": f"The accepted {source_event['id']} event produced this evidence.",
                "relevant_actor_ids": source_event["actor_ids"],
                "occurred_minute": source_event["minute"],
                "discovery": discovery,
                "prerequisite_role_ids": [],
                "difficulty": source["difficulty"],
                "manipulable": source["manipulable"],
                "essential": True,
            }
        proof_routes.append(
            {
                "label": route["label"],
                **claims,
                "timeline_fact_ids": list(claims["opportunity"]["fact_ids"]),
                "independence_rationale": (
                    "This route uses its own three evidence roles and provenance chain."
                ),
            }
        )

    timeline.sort(key=lambda event: (event["minute"], event["id"]))

    from game.case_generation import (
        GeneratedCrimeTimelineStage,
        build_proof_support_catalog,
        proof_support_catalog_fingerprint,
    )

    core_payload = {
        "schema_version": 1,
        **{
            key: case[key]
            for key in (
                "title",
                "investigation_start_minute",
                "murder",
                "facts",
                "opening",
            )
        },
        "timeline": timeline,
    }
    core_stage = GeneratedCrimeTimelineStage.model_validate(core_payload)
    proof_catalog = build_proof_support_catalog(core_stage)
    selection_routes: list[dict[str, object]] = []
    for route_index, route in enumerate(proof_routes, start=1):
        selections: dict[str, object] = {}
        for axis in ("method", "motive", "opportunity"):
            claim = route[axis]
            candidate = next(
                value
                for value in proof_catalog.candidates.values()
                if value.axis == axis
                and set(claim["fact_ids"]) <= set(value.fact_ids)
                and value.source_event_id == claim["source_event_ids"][0]
            )
            claim["fact_ids"] = list(candidate.fact_ids)
            realizations[f"route_{route_index}_{axis}"]["supported_fact_ids"] = list(
                candidate.fact_ids
            )
            selections[axis] = {
                "support_candidate_id": candidate.candidate_id,
                "claim": claim["claim"],
                "evidence_role_summary": claim["evidence_role_summary"],
                "required_form": claim["required_form"],
            }
        selection_routes.append(
            {
                "label": route["label"],
                **selections,
                "independence_rationale": route["independence_rationale"],
            }
        )

    red_sources = [
        (evidence_id, item)
        for evidence_id, item in evidence.items()
        if item["is_red_herring"]
    ][:2]
    innocents = [
        character_id
        for character_id in case["overlays"]
        if character_id not in {case["murder"]["murderer_id"], case["murder"]["victim_id"]}
    ]
    misdirection: dict[str, dict[str, object]] = {}
    for index, (_evidence_id, source) in enumerate(red_sources, start=1):
        key = f"misdirection_{index}"
        source_event = event_for(list(source["fact_ids"]))
        if source["initial_slot_id"]:
            discovery = {"kind": "slot", "target_id": source["initial_slot_id"]}
        else:
            discovery = {"kind": "body", "target_id": "body"}
        implications = list(source["implicates_character_ids"])
        exonerations = (
            [next(value for value in innocents if value not in implications)]
            if index == 1
            else []
        )
        secret_fact_ids = [
            fact_id
            for fact_id in source["fact_ids"]
            if facts[fact_id]["category"] == "secret"
        ]
        misdirection[key] = {
            "misdirection_id": key,
            "name": source["name"],
            "description": source["description"],
            "kind": source["kind"],
            "fact_ids": source["fact_ids"],
            "source_event_id": source_event["id"],
            "causal_origin": source["red_herring_explanation"],
            "relevant_actor_ids": source_event["actor_ids"],
            "occurred_minute": source_event["minute"],
            "discovery": discovery,
            "prerequisite_role_ids": [],
            "implicates_character_ids": implications,
            "exonerates_character_ids": exonerations,
            "contradiction_fact_ids": list(source["fact_ids"]) if index == 1 else [],
            "secondary_secret_fact_ids": secret_fact_ids,
            "red_herring_explanation": source["red_herring_explanation"],
            "difficulty": source["difficulty"],
            "manipulable": source["manipulable"],
        }

    overlays = deepcopy(case["overlays"])
    for overlay in overlays.values():
        overlay["supporting_evidence_ids"] = []
    return {
        "case_generation_core": core_payload,
        "case_generation_proof_blueprint": {
            "schema_version": 1,
            "culprit_id": solution["culprit_id"],
            "proof_catalog_fingerprint": proof_support_catalog_fingerprint(proof_catalog),
            "routes": selection_routes,
        },
        "case_generation_evidence_realization": {
            "schema_version": 1,
            "realizations": realizations,
        },
        "case_generation_misdirection": {
            "schema_version": 1,
            "misdirection": misdirection,
        },
        "case_generation_overlays": {"schema_version": 1, "overlays": overlays},
        "case_generation_presentation": {
            "schema_version": 1,
            "presentation": document["presentation"],
        },
    }


def generated_stage_response(
    document: dict[str, object],
    task_role: str,
) -> dict[str, object]:
    """Return the provider payload for one bounded scenario-generation stage."""

    payloads = generated_stage_payloads(document)
    if task_role in payloads:
        return deepcopy(payloads[task_role])
    raise AssertionError(f"unexpected scenario stage: {task_role}")


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
