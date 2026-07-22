"""Provider-free semantic Stage 1 plus valid downstream deltas for regressions."""

from __future__ import annotations

import json

from game.case_generation import (
    GeneratedCrimeTimelineStage,
    GeneratedMisdirectionConnectiveStage,
    GeneratedProofRouteSelectionStage,
    build_proof_support_catalog,
    compile_proof_route_selection,
    proof_support_catalog_fingerprint,
)
from game.content import load_case, load_location
from game.stage1_semantic import (
    Stage1RoleAssignment,
    Stage1SemanticPlan,
    build_stage1_alias_map,
    build_stage1_semantic_messages,
    compile_stage1_semantic_plan,
    select_stage1_roles,
)


def semantic_pipeline_payloads(
    seed: int = 901,
    *,
    character_ids: tuple[str, ...] | None = None,
    semantic_plan: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    source = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    selected_ids = character_ids or source.character_ids
    aliases = build_stage1_alias_map(selected_ids, location)
    if semantic_plan is None:
        roles = select_stage1_roles(character_ids=selected_ids, seed=seed)
        messages = build_stage1_semantic_messages(
            character_ids=selected_ids,
            location=location,
            assignment=roles,
            aliases=aliases,
        )
        plan = Stage1SemanticPlan.model_validate(
            json.loads(messages[1].content)["valid_example"]
        )
    else:
        plan = Stage1SemanticPlan.model_validate(semantic_plan)
        roles = Stage1RoleAssignment(
            death_mode=plan.fixed_roles.death_mode,
            victim_id=aliases.alias_to_character[plan.fixed_roles.victim_ref],
            responsible_actor_id=aliases.alias_to_character[
                plan.fixed_roles.responsible_actor_ref
            ],
            discoverer_id=aliases.alias_to_character[plan.fixed_roles.discoverer_ref],
        )
    core = GeneratedCrimeTimelineStage.model_validate(
        compile_stage1_semantic_plan(
            plan,
            assignment=roles,
            aliases=aliases,
            location=location,
        )
    )
    catalog = build_proof_support_catalog(core)
    candidates_by_axis = {
        axis: sorted(
            (
                candidate
                for candidate in catalog.candidates.values()
                if candidate.axis == axis
            ),
            key=lambda item: item.candidate_id,
        )
        for axis in ("method", "motive", "opportunity")
    }
    routes: list[dict[str, object]] = []
    forms = (("physical", "testimonial", "documentary"), ("documentary", "behavioural", "physical"))
    for route_index in range(2):
        selections: dict[str, object] = {}
        for axis_index, axis in enumerate(("method", "motive", "opportunity")):
            candidates = candidates_by_axis[axis]
            candidate = candidates[min(route_index, len(candidates) - 1)]
            selections[axis] = {
                "support_candidate_id": candidate.candidate_id,
                "claim": f"Route {route_index + 1} {axis} claim from accepted Stage 1 semantics.",
                "evidence_role_summary": f"Independent {forms[route_index][axis_index]} realization for {axis}.",
                "required_form": forms[route_index][axis_index],
            }
        routes.append(
            {
                "label": f"Semantic route {route_index + 1}",
                **selections,
                "independence_rationale": "The route uses a distinct evidence form or causal event on every proof axis.",
            }
        )
    proof_selection = GeneratedProofRouteSelectionStage.model_validate(
        {
            "schema_version": 1,
            "culprit_id": core.murder.murderer_id,
            "proof_catalog_fingerprint": proof_support_catalog_fingerprint(catalog),
            "routes": routes,
        }
    )
    proof = compile_proof_route_selection(proof_selection, catalog=catalog, core=core)

    slots = [
        "slot_hall_clock",
        "slot_hall_coats",
        "slot_drawing_trolley",
        "slot_drawing_sofa",
        "slot_library_desk",
        "slot_library_fireplace",
        "slot_library_clock",
        "slot_library_atlas",
    ]
    realizations: dict[str, dict[str, object]] = {}
    slot_index = 0
    for route_index, route in enumerate(proof.routes, start=1):
        for axis in ("method", "motive", "opportunity"):
            role_id = f"route_{route_index}_{axis}"
            claim = getattr(route, axis)
            event = next(
                event for event in core.timeline if event.id == claim.source_event_ids[0]
            )
            realizations[role_id] = {
                "role_id": role_id,
                "route_id": f"route_{route_index}",
                "axis": axis,
                "name": f"Semantic {axis} trace {route_index}",
                "description": f"A concrete trace supporting the accepted {axis} claim.",
                "kind": claim.required_form.value,
                "supported_fact_ids": list(claim.fact_ids),
                "source_event_id": event.id,
                "causal_origin": "The accepted causal event produced this trace.",
                "relevant_actor_ids": list(event.actor_ids),
                "occurred_minute": event.minute,
                "discovery": {"kind": "slot", "target_id": slots[slot_index]},
                "prerequisite_role_ids": [],
                "difficulty": 2,
                "manipulable": False,
                "essential": True,
            }
            slot_index += 1

    secret_fact = next(
        fact for fact in core.facts.values() if fact.category.value == "secret"
    )
    secret_event = next(
        event for event in core.timeline if secret_fact.id in event.fact_ids
    )
    innocents = [
        character_id
        for character_id in selected_ids
        if character_id not in {core.murder.victim_id, core.murder.murderer_id}
    ]
    misdirection = {
        "misdirection_1": {
            "misdirection_id": "misdirection_1",
            "name": "Concealed private trace",
            "description": "A trace of an innocent survivor's separate concealed act.",
            "kind": "physical",
            "fact_ids": [secret_fact.id],
            "source_event_id": secret_event.id,
            "causal_origin": "The innocent private act created this trace without causing the death.",
            "relevant_actor_ids": list(secret_event.actor_ids),
            "occurred_minute": secret_event.minute,
            "discovery": {"kind": "slot", "target_id": slots[6]},
            "prerequisite_role_ids": [],
            "implicates_character_ids": [innocents[0]],
            "exonerates_character_ids": [],
            "contradiction_fact_ids": [secret_fact.id],
            "secondary_secret_fact_ids": [secret_fact.id],
            "red_herring_explanation": "It records a separate private act, not the murder.",
            "difficulty": 2,
            "manipulable": False,
        },
        "misdirection_2": {
            "misdirection_id": "misdirection_2",
            "name": "Misread private trace",
            "description": "A second reading of the same innocent secret initially misdirects suspicion.",
            "kind": "testimonial",
            "fact_ids": [secret_fact.id],
            "source_event_id": secret_event.id,
            "causal_origin": "A witness interpretation exaggerates the significance of the innocent act.",
            "relevant_actor_ids": list(secret_event.actor_ids),
            "occurred_minute": secret_event.minute,
            "discovery": {"kind": "slot", "target_id": slots[7]},
            "prerequisite_role_ids": [],
            "implicates_character_ids": [innocents[1]],
            "exonerates_character_ids": [innocents[0]],
            "contradiction_fact_ids": [],
            "secondary_secret_fact_ids": [],
            "red_herring_explanation": "The interpretation is mistaken and has a non-murder explanation.",
            "difficulty": 2,
            "manipulable": False,
        },
    }
    GeneratedMisdirectionConnectiveStage.model_validate(
        {"schema_version": 1, "misdirection": misdirection}
    )

    overlays: dict[str, dict[str, object]] = {}
    first_fact_id = next(iter(core.facts))
    survivors = [
        character_id
        for character_id in selected_ids
        if character_id != core.murder.victim_id
    ]
    for character_index, character_id in enumerate(selected_ids):
        role = (
            "victim"
            if character_id == core.murder.victim_id
            else "murderer"
            if character_id == core.murder.murderer_id
            else "innocent"
        )
        starting_room_id = (
            core.murder.room_id
            if role == "victim"
            else core.opening.post_meeting_room_ids[character_id]
        )
        schedule = [
            {
                "start_minute": event.minute,
                "end_minute": event.minute + 1,
                "room_id": event.room_id,
                "activity": f"Participates in accepted causal event {event.id}.",
                "witnessed_by": [],
            }
            for event in core.timeline
            if character_id in event.actor_ids
        ]
        observation_minute = core.investigation_start_minute + 20 + character_index * 2
        if role != "victim":
            schedule.append(
                {
                    "start_minute": observation_minute,
                    "end_minute": observation_minute + 1,
                    "room_id": starting_room_id,
                    "activity": f"Privately considers detail {character_index}.",
                    "witnessed_by": [],
                }
            )
        schedule.sort(key=lambda item: item["start_minute"])
        target = next(
            value for value in selected_ids if value != character_id
        )
        suspicion_target = next(
            value
            for value in survivors
            if value != character_id
        ) if character_id in survivors and len(survivors) > 1 else target
        overlays[character_id] = {
            "character_id": character_id,
            "role": role,
            "starting_room_id": starting_room_id,
            "public_relationship_to_victim": "A guest with a known connection to the victim.",
            "private_motive": f"Private pressure unique to {character_id} creates plausible conflict.",
            "secrets": [] if role == "victim" else [f"{character_id} withholds a distinct private concern."],
            "schedule": schedule,
            "observations": [] if role == "victim" else [
                {
                    "id": f"observation_{character_index}",
                    "minute": observation_minute,
                    "room_id": starting_room_id,
                    "summary": f"{character_id} privately notices a distinct contextual detail.",
                    "fact_ids": [first_fact_id],
                    "certainty": 0.7,
                }
            ],
            "alibi_claim": "I was elsewhere and did not understand what had happened.",
            "alibi_disclosed_fact_ids": [],
            "alibi_type": "false" if role == "murderer" else "incomplete",
            "supporting_evidence_ids": [],
            "goals": [] if role == "victim" else [f"Protect {character_id}'s distinct interest while learning the truth."],
            "hides_fact_ids": [],
            "lies": [],
            "relationships": [] if role == "victim" else [
                {
                    "target_character_id": target,
                    "public_summary": "They are acquainted through the closed circle.",
                    "private_summary": f"{character_id} privately distrusts {target} for a unique reason.",
                    "affinity": -10 - character_index,
                }
            ],
            "initial_emotional_state": "deceased" if role == "victim" else f"guarded-{character_index}",
            "initial_suspicions": {} if role == "victim" else {suspicion_target: 10 + character_index},
        }

    presentation = {
        "title": "The Quiet Gathering",
        "tagline": "Eight guests wait behind closed doors as the storm deepens.",
        "public_opening": "An alarm has gathered the surviving guests in the great hall. The house remains isolated until morning.",
        "atmosphere": "Rain presses against old glass while corridors and public rooms settle into uneasy silence.",
        "character_tensions": [
            {
                "character_id": character_id,
                "public_hook": f"Guest {index + 1} arrived with an unresolved public obligation.",
            }
            for index, character_id in enumerate(selected_ids)
        ],
        "room_flavour": [
            {
                "room_id": room_id,
                "text": f"Room {index + 1} carries the restrained atmosphere of a storm-bound estate.",
            }
            for index, room_id in enumerate(location.rooms)
        ],
    }
    return {
        "stage1_semantic_plan": plan.model_dump(mode="json"),
        "case_generation_core": core.model_dump(mode="json"),
        "case_generation_proof_blueprint": proof_selection.model_dump(mode="json"),
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
            "presentation": presentation,
        },
    }
