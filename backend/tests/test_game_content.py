"""Structural tests for the authoritative turn-based content foundation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from game.content import (
    CASES_DIR,
    CHARACTER_CARDS_DIR,
    LOCATIONS_DIR,
    list_content_ids,
    load_case,
    load_character_card,
    load_location,
)
from game.models import CaseDefinition, CharacterRole


EXPECTED_CAST = {
    "lady_vivienne_ashford",
    "edgar_blackwood",
    "dr_celestine_moreau",
    "inspector_elena_hayes",
    "captain_marcus_drake",
    "chef_armand_dubois",
    "sabrina_voss",
    "zara_okonkwo",
}


def test_content_id_resolution_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        load_location("../ashwick_manor")


def test_ashwick_location_package_references_resolve() -> None:
    location = load_location("ashwick_manor")

    assert location.assembly_room_id in location.rooms
    assert len(location.rooms) == 9
    assert set(location.body_discovery_room_ids) <= set(location.rooms)
    assert all(location.rooms[room_id].body_discovery_allowed for room_id in location.body_discovery_room_ids)

    for key, room in location.rooms.items():
        assert key == room.id
        assert set(room.searchable_object_ids) <= set(location.searchable_objects)

    adjacency = {room_id: set() for room_id in location.rooms}
    for door in location.doors:
        assert door.room_a_id in location.rooms
        assert door.room_b_id in location.rooms
        assert door.room_a_id != door.room_b_id
        adjacency[door.room_a_id].add(door.room_b_id)
        if not door.one_way:
            adjacency[door.room_b_id].add(door.room_a_id)
        if door.key_item_id:
            assert door.key_item_id in location.items

    visited = {location.assembly_room_id}
    frontier = [location.assembly_room_id]
    while frontier:
        room_id = frontier.pop()
        for neighbour in adjacency[room_id] - visited:
            visited.add(neighbour)
            frontier.append(neighbour)
    assert visited == set(location.rooms), "the playable room graph must be connected"

    for key, searchable in location.searchable_objects.items():
        assert key == searchable.id
        assert searchable.room_id in location.rooms
        assert set(searchable.evidence_slot_ids) <= set(location.evidence_slots)
        if searchable.requires_item_id:
            assert searchable.requires_item_id in location.items

    for key, slot in location.evidence_slots.items():
        assert key == slot.id
        assert slot.room_id in location.rooms
        assert slot.object_id in location.searchable_objects
        assert location.searchable_objects[slot.object_id].room_id == slot.room_id

    for key, weapon in location.potential_weapons.items():
        assert key == weapon.id
        assert weapon.room_id in location.rooms
        assert weapon.object_id in location.searchable_objects
        assert location.searchable_objects[weapon.object_id].room_id == weapon.room_id

    for key, item in location.items.items():
        assert key == item.id
        assert item.initial_slot_id in location.evidence_slots
        assert set(item.access_object_ids) <= set(location.searchable_objects)
        assert set(item.access_door_ids) <= {door.id for door in location.doors}

    for rule in location.murder_opportunity_rules:
        assert set(rule.room_ids) <= set(location.rooms)
        assert set(rule.weapon_ids) <= set(location.potential_weapons)
        weapon_methods = {
            method
            for weapon_id in rule.weapon_ids
            for method in location.potential_weapons[weapon_id].compatible_methods
        }
        assert set(rule.compatible_methods) <= weapon_methods


def test_authored_location_is_deeply_immutable() -> None:
    location = load_location("ashwick_manor")

    with pytest.raises(ValidationError):
        location.name = "Changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        location.rooms["new_room"] = location.rooms["library"]
    with pytest.raises(TypeError):
        location.rooms["library"].searchable_object_ids[0] = "changed"


def test_location_round_trips_without_serializer_warnings() -> None:
    location = load_location("ashwick_manor")
    encoded = location.model_dump_json(warnings="error")
    assert load_location("ashwick_manor") == location
    assert "Ashwick Manor" in encoded


def test_exactly_eight_playable_ccv3_cards_load() -> None:
    card_ids = set(list_content_ids(CHARACTER_CARDS_DIR))
    assert card_ids == EXPECTED_CAST

    cards = {character_id: load_character_card(character_id) for character_id in card_ids}
    assert {card.spec for card in cards.values()} == {"chara_card_v3"}
    assert {card.spec_version for card in cards.values()} == {"3.0"}
    assert len({card.data.name for card in cards.values()}) == 8
    for card in cards.values():
        extension = card.data.extensions.murder_mystery
        assert extension.values
        assert extension.fears
        assert extension.deception_tendency
        assert extension.behavioural_constraints
        assert card.data.group_only_greetings == ()
        icons = [asset for asset in card.data.assets if asset.type == "icon"]
        assert len(icons) == 1
        assert icons[0].name == "main"
        assert card.data.character_book is not None
        orders = [entry.insertion_order for entry in card.data.character_book.entries]
        assert orders == sorted(orders)
        assert all(not entry.use_regex for entry in card.data.character_book.entries)


def test_deterministic_case_fixture_references_resolve() -> None:
    case = load_case("ashwick_sample")
    location = load_location(case.location_package_id)
    cast = set(case.character_ids)

    assert cast == EXPECTED_CAST
    assert set(case.overlays) == cast
    assert case.murder.victim_id in cast
    assert case.murder.murderer_id in cast
    assert case.murder.victim_id != case.murder.murderer_id
    assert case.murder.room_id in location.rooms
    assert case.murder.weapon_id in location.potential_weapons
    assert case.initial_player_room_id in location.rooms

    roles = [overlay.role for overlay in case.overlays.values()]
    assert roles.count(CharacterRole.VICTIM) == 1
    assert roles.count(CharacterRole.MURDERER) == 1
    assert roles.count(CharacterRole.INNOCENT) == 6
    assert case.overlays[case.murder.victim_id].role == CharacterRole.VICTIM
    assert case.overlays[case.murder.murderer_id].role == CharacterRole.MURDERER

    assert list(case.timeline) == sorted(case.timeline, key=lambda event: event.minute)
    for key, fact in case.facts.items():
        assert key == fact.id
        assert set(fact.related_character_ids) <= cast
        assert set(fact.related_evidence_ids) <= set(case.evidence)

    for event in case.timeline:
        assert event.room_id in location.rooms
        assert set(event.actor_ids) <= cast
        assert set(event.observed_by) <= cast
        assert set(event.fact_ids) <= set(case.facts)

    for key, overlay in case.overlays.items():
        assert key == overlay.character_id
        assert overlay.starting_room_id in location.rooms
        assert set(overlay.supporting_evidence_ids) <= set(case.evidence)
        assert set(overlay.hides_fact_ids) <= set(case.facts)
        assert set(overlay.initial_suspicions) <= cast - {key}
        for schedule in overlay.schedule:
            assert schedule.start_minute < schedule.end_minute
            assert schedule.room_id in location.rooms
            assert set(schedule.witnessed_by) <= cast - {key}
        for observation in overlay.observations:
            assert observation.room_id in location.rooms
            assert set(observation.fact_ids) <= set(case.facts)
        for lie in overlay.lies:
            assert set(lie.contradicts_fact_ids) <= set(case.facts)

    for key, evidence in case.evidence.items():
        assert key == evidence.id
        if evidence.initial_slot_id:
            assert evidence.initial_slot_id in location.evidence_slots
        assert set(evidence.fact_ids) <= set(case.facts)
        assert set(evidence.implicates_character_ids) <= cast
        assert set(evidence.exonerates_character_ids) <= cast
        assert set(evidence.prerequisite_evidence_ids) <= set(case.evidence) - {key}
        if evidence.is_red_herring:
            assert evidence.red_herring_explanation

    opening = case.opening
    assert opening.discoverer_id in cast - {case.murder.victim_id}
    assert opening.body_room_id == case.murder.room_id
    assert opening.assembly_room_id == location.assembly_room_id
    assert set(opening.initial_reactions) == cast - {
        case.murder.victim_id,
        opening.discoverer_id,
    }
    assert set(opening.post_meeting_room_ids) == cast - {case.murder.victim_id}
    assert set(opening.post_meeting_room_ids.values()) <= set(location.rooms)

    solution_evidence = (
        set(case.solution.method_evidence_ids)
        | set(case.solution.motive_evidence_ids)
        | set(case.solution.opportunity_evidence_ids)
    )
    assert case.solution.culprit_id == case.murder.murderer_id
    assert solution_evidence <= set(case.evidence)
    assert set(case.solution.timeline_fact_ids) <= set(case.facts)
    groups = {case.evidence[evidence_id].redundancy_group for evidence_id in solution_evidence}
    assert len(groups) >= case.solution.independent_evidence_groups_required


def test_content_catalog_has_one_location_and_one_deterministic_case() -> None:
    assert list_content_ids(LOCATIONS_DIR) == ["ashwick_manor"]
    assert list_content_ids(CASES_DIR) == ["ashwick_sample"]
