"""Independent provider-shaped fixture for generated-case acceptance tests.

This document is deliberately authored here from public Ashwick location IDs.
It does not load, copy, transform, or remap either authored crime spine.
"""

from __future__ import annotations


ARBITRARY_CAST = (
    "captain_marcus_drake",
    "gabriel_cross",
    "celia_marlowe",
    "chef_armand_dubois",
    "commander_elias_ward",
    "countess_beatrice_harrow",
    "dr_amara_sen",
    "inspector_maeve_quinn",
)

VICTIM_ID = "captain_marcus_drake"
MURDERER_ID = "gabriel_cross"
DISCOVERER_ID = "inspector_maeve_quinn"


def independent_generated_document() -> dict[str, object]:
    """Return a complete generated document with its own crime and clue graph."""

    facts = {
        "acceptance_means": {
            "id": "acceptance_means",
            "category": "means",
            "statement": "Fresh square impact damage marks the recovered fireplace poker.",
            "related_character_ids": [MURDERER_ID],
            "related_evidence_ids": ["acceptance_poker", "acceptance_metal_trace"],
        },
        "acceptance_motive": {
            "id": "acceptance_motive",
            "category": "motive",
            "statement": "The estate accounts show Cross faced exposure over diverted restoration funds.",
            "related_character_ids": [MURDERER_ID],
            "related_evidence_ids": ["acceptance_accounts", "acceptance_demand"],
        },
        "acceptance_opportunity_a": {
            "id": "acceptance_opportunity_a",
            "category": "opportunity",
            "statement": "The stopped mantel clock fixes Cross in the library during an unobserved interval.",
            "related_character_ids": [MURDERER_ID],
            "related_evidence_ids": ["acceptance_clock"],
        },
        "acceptance_timeline_a": {
            "id": "acceptance_timeline_a",
            "category": "timeline",
            "statement": "The mantel clock stopped at 22:00 during the private meeting.",
            "related_character_ids": [MURDERER_ID, VICTIM_ID],
            "related_evidence_ids": ["acceptance_clock"],
        },
        "acceptance_opportunity_b": {
            "id": "acceptance_opportunity_b",
            "category": "opportunity",
            "statement": "A hall route note places Cross alone between the meeting and the alarm.",
            "related_character_ids": [MURDERER_ID],
            "related_evidence_ids": ["acceptance_route_note"],
        },
        "acceptance_timeline_b": {
            "id": "acceptance_timeline_b",
            "category": "timeline",
            "statement": "The route note records Cross returning after the alarm sounded.",
            "related_character_ids": [MURDERER_ID],
            "related_evidence_ids": ["acceptance_route_note"],
        },
        "acceptance_red_herring_a": {
            "id": "acceptance_red_herring_a",
            "category": "context",
            "statement": "A torn menu records an unrelated argument after dinner.",
            "related_character_ids": ["celia_marlowe"],
            "related_evidence_ids": ["acceptance_menu"],
        },
        "acceptance_red_herring_b": {
            "id": "acceptance_red_herring_b",
            "category": "secret",
            "statement": "A pressed flower hides a private but harmless correspondence.",
            "related_character_ids": ["countess_beatrice_harrow"],
            "related_evidence_ids": ["acceptance_flower"],
        },
    }
    living_ids = tuple(
        character_id for character_id in ARBITRARY_CAST if character_id != VICTIM_ID
    )
    for index, character_id in enumerate(living_ids):
        display_name = character_id.replace("_", " ").title()
        fact_id = f"acceptance_private_{index}"
        facts[fact_id] = {
            "id": fact_id,
            "category": "secret",
            "statement": f"{display_name} privately recorded concern number {index + 1} before dinner.",
            "related_character_ids": [character_id],
            "related_evidence_ids": [],
        }

    def evidence(
        evidence_id: str,
        name: str,
        slot_id: str,
        fact_ids: list[str],
        group: str,
        *,
        implicates: list[str] | None = None,
        red_herring: bool = False,
    ) -> dict[str, object]:
        object_id = {
            "slot_library_fireplace": "library_fireplace",
            "slot_hall_coats": "hall_coat_stand",
            "slot_study_desk": "study_desk",
            "slot_drawing_sofa": "drawing_sofa",
            "slot_library_clock": "library_clock",
            "slot_hall_clock": "hall_clock",
            "slot_dining_table": "dining_table",
            "slot_conservatory_bench": "conservatory_bench",
        }[slot_id]
        return {
            "id": evidence_id,
            "name": name,
            "kind": "physical",
            "description": f"A documented acceptance-case item: {name}.",
            "initial_slot_id": slot_id,
            "fact_ids": fact_ids,
            "implicates_character_ids": implicates or [],
            "exonerates_character_ids": [],
            "is_red_herring": red_herring,
            "red_herring_explanation": (
                "It documents a separate social dispute, not the fatal encounter."
                if red_herring
                else ""
            ),
            "discoverable_via": [f"search:{object_id}"],
            "difficulty": 1,
            "manipulable": False,
            "essential": not red_herring,
            "redundancy_group": group,
            "prerequisite_evidence_ids": [],
        }

    evidence_items = {
        "acceptance_poker": evidence("acceptance_poker", "Damaged poker", "slot_library_fireplace", ["acceptance_means"], "means_a", implicates=[MURDERER_ID]),
        "acceptance_metal_trace": evidence("acceptance_metal_trace", "Metal trace", "slot_hall_coats", ["acceptance_means"], "means_b", implicates=[MURDERER_ID]),
        "acceptance_accounts": evidence("acceptance_accounts", "Restoration accounts", "slot_study_desk", ["acceptance_motive"], "motive_a", implicates=[MURDERER_ID]),
        "acceptance_demand": evidence("acceptance_demand", "Payment demand", "slot_drawing_sofa", ["acceptance_motive"], "motive_b", implicates=[MURDERER_ID]),
        "acceptance_clock": evidence("acceptance_clock", "Stopped mantel clock", "slot_library_clock", ["acceptance_opportunity_a", "acceptance_timeline_a"], "opportunity_a", implicates=[MURDERER_ID]),
        "acceptance_route_note": evidence("acceptance_route_note", "Route note", "slot_hall_clock", ["acceptance_opportunity_b", "acceptance_timeline_b"], "opportunity_b", implicates=[MURDERER_ID]),
        "acceptance_menu": evidence("acceptance_menu", "Torn dinner menu", "slot_dining_table", ["acceptance_red_herring_a"], "red_a", implicates=["celia_marlowe"], red_herring=True),
        "acceptance_flower": evidence("acceptance_flower", "Pressed flower", "slot_conservatory_bench", ["acceptance_red_herring_b"], "red_b", implicates=["countess_beatrice_harrow"], red_herring=True),
    }
    evidence_items["acceptance_metal_trace"]["manipulable"] = True

    rooms = {
        VICTIM_ID: "library",
        MURDERER_ID: "library",
        "celia_marlowe": "drawing_room",
        "chef_armand_dubois": "kitchen",
        "commander_elias_ward": "gallery",
        "countess_beatrice_harrow": "conservatory",
        "dr_amara_sen": "chapel",
        DISCOVERER_ID: "library",
    }

    def overlay(character_id: str) -> dict[str, object]:
        role = "victim" if character_id == VICTIM_ID else "murderer" if character_id == MURDERER_ID else "innocent"
        schedule_room = rooms[character_id]
        if role == "victim":
            private_fact_id = None
            target_id = None
            observations: list[dict[str, object]] = []
        else:
            private_index = living_ids.index(character_id)
            private_fact_id = f"acceptance_private_{private_index}"
            target_id = living_ids[(private_index + 1) % len(living_ids)]
            observations = [{
                "id": f"acceptance_private_observation_{private_index}",
                "minute": 60,
                "room_id": schedule_room if character_id != DISCOVERER_ID else "drawing_room",
                "summary": f"I remember the private concern I recorded before dinner ({private_index + 1}).",
                "fact_ids": [private_fact_id],
                "certainty": 0.7 + private_index * 0.03,
            }]
        if character_id == DISCOVERER_ID:
            observations.append({
                "id": "acceptance_maeve_clock",
                "minute": 140,
                "room_id": "library",
                "summary": "I found the mantel clock stopped when I entered the library.",
                "fact_ids": ["acceptance_timeline_a"],
                "certainty": 0.9,
            })
        schedule = (
            [
                {"start_minute": 0, "end_minute": 130, "room_id": "drawing_room", "activity": "A private evening engagement.", "witnessed_by": []},
                {"start_minute": 130, "end_minute": 180, "room_id": "library", "activity": "Checking the library after hearing a disturbance.", "witnessed_by": []},
            ]
            if character_id == DISCOVERER_ID
            else [{"start_minute": 0, "end_minute": 180, "room_id": schedule_room, "activity": "A private evening engagement.", "witnessed_by": []}]
        )
        private_index = living_ids.index(character_id) if role != "victim" else -1
        return {
            "character_id": character_id,
            "role": role,
            "starting_room_id": "great_hall",
            "public_relationship_to_victim": "A guest with an unfinished connection to the captain.",
            "private_motive": f"{character_id.replace('_', ' ').title()} feared a private loss tied to the captain's decisions.",
            "secrets": ([] if role == "victim" else [f"{character_id.replace('_', ' ').title()} concealed a distinct personal concern numbered {private_index + 1}."]),
            "schedule": schedule,
            "observations": observations,
            "alibi_claim": "I was occupied elsewhere when the disturbance began.",
            "alibi_type": "incomplete",
            "alibi_disclosed_fact_ids": [],
            "supporting_evidence_ids": [],
            "goals": ([] if role == "victim" else [f"Resolve private objective {private_index + 1} without public embarrassment.", f"Learn why {target_id.replace('_', ' ')} is watching the room."]),
            "hides_fact_ids": ([] if private_fact_id is None else [private_fact_id]),
            "lies": [],
            "relationships": ([] if target_id is None else [{
                "target_character_id": target_id,
                "public_summary": "They disagree over the evening's arrangements.",
                "private_summary": f"A private dispute numbered {private_index + 1} has damaged their trust.",
                "affinity": -10 - private_index * 7,
            }]),
            "initial_emotional_state": "composed" if role == "victim" else f"guarded-{private_index + 1}",
            "initial_suspicions": ({} if target_id is None else {target_id: 10 + private_index * 5}),
        }

    return {
        "schema_version": 1,
        "case": {
            "schema_version": 1,
            "title": "The Lantern Ledger",
            "investigation_start_minute": 150,
            "murder": {
                "victim_id": VICTIM_ID,
                "murderer_id": MURDERER_ID,
                "method": "blunt_force",
                "means": "A fireplace poker was used during a private meeting.",
                "weapon_id": "library_poker",
                "motive": "Cross acted to prevent exposure of diverted restoration funds.",
                "minute": 120,
                "room_id": "library",
                "opportunity": "The library meeting created an unobserved interval.",
                "cover_story": "Cross claims to have remained in the great hall.",
            },
            "facts": facts,
            "timeline": [
                {"id": "acceptance_meeting", "minute": 90, "event_type": "meeting", "room_id": "library", "actor_ids": [VICTIM_ID, MURDERER_ID], "summary": "A private financial meeting begins.", "fact_ids": ["acceptance_motive"], "observed_by": []},
                {"id": "acceptance_murder", "minute": 120, "event_type": "murder", "room_id": "library", "actor_ids": [VICTIM_ID, MURDERER_ID], "summary": "The meeting ends in violence.", "fact_ids": ["acceptance_means", "acceptance_opportunity_a", "acceptance_timeline_a"], "observed_by": []},
                {"id": "acceptance_discovery", "minute": 140, "event_type": "discovery", "room_id": "library", "actor_ids": [DISCOVERER_ID], "summary": "A guest finds the captain after the storm surge.", "fact_ids": ["acceptance_timeline_b"], "observed_by": []},
            ],
            "overlays": {character_id: overlay(character_id) for character_id in ARBITRARY_CAST},
            "evidence": evidence_items,
            "opening": {
                "discoverer_id": DISCOVERER_ID,
                "discovery_minute": 140,
                "body_room_id": "library",
                "post_meeting_room_ids": {character_id: rooms[character_id] for character_id in ARBITRARY_CAST if character_id != VICTIM_ID},
            },
            "solution": {
                "culprit_id": MURDERER_ID,
                "method_evidence_ids": ["acceptance_poker", "acceptance_metal_trace"],
                "motive_evidence_ids": ["acceptance_accounts", "acceptance_demand"],
                "opportunity_evidence_ids": ["acceptance_clock", "acceptance_route_note"],
                "timeline_fact_ids": ["acceptance_timeline_a", "acceptance_timeline_b"],
                "independent_evidence_groups_required": 3,
                "evidence_routes": [
                    {
                        "id": "lantern_documentary_route",
                        "label": "The weapon, accounts, and stopped-clock route",
                        "method_evidence_ids": ["acceptance_poker"],
                        "motive_evidence_ids": ["acceptance_accounts"],
                        "opportunity_evidence_ids": ["acceptance_clock"],
                        "timeline_fact_ids": ["acceptance_timeline_a"],
                    },
                    {
                        "id": "lantern_trace_route",
                        "label": "The transferred trace, demand, and return-route route",
                        "method_evidence_ids": ["acceptance_metal_trace"],
                        "motive_evidence_ids": ["acceptance_demand"],
                        "opportunity_evidence_ids": ["acceptance_route_note"],
                        "timeline_fact_ids": ["acceptance_timeline_b"],
                    },
                ],
            },
        },
        "presentation": {
            "title": "Lanterns at Ashwick",
            "tagline": "Rain closes the road while old tensions surface.",
            "public_opening": "The flooded causeway leaves the house cut off until morning.",
            "atmosphere": "Wind worries the windows and lantern light moves across old wood.",
            "character_tensions": [{"character_id": character_id, "public_hook": "A past disagreement has made the evening uncomfortable."} for character_id in ARBITRARY_CAST],
            "room_flavour": [{"room_id": room_id, "text": "Storm light changes the familiar room."} for room_id in ("great_hall", "drawing_room", "library", "study", "dining_room", "kitchen", "gallery", "conservatory", "chapel")],
        },
    }
