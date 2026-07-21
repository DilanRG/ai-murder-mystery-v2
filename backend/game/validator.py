"""Cross-document validation for authored locations and mystery cases.

Pydantic verifies the shape of each document.  This module verifies the
relationships that only make sense once a case is paired with its location.
It deliberately returns *all* findings so content authors can fix a package in
one editing pass.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable

from game.models import CaseDefinition, CharacterRole, LocationPackage


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One actionable authored-content problem."""

    code: str
    path: str
    message: str


@dataclass(slots=True)
class ValidationReport:
    """The complete result of validating a content package."""

    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.issues

    @property
    def valid(self) -> bool:
        """Compatibility-friendly spelling for callers that prefer ``valid``."""
        return self.is_valid

    def add(self, code: str, path: str, message: str) -> None:
        self.issues.append(ValidationIssue(code, path, message))

    def extend(self, other: "ValidationReport") -> None:
        self.issues.extend(other.issues)

    def __bool__(self) -> bool:
        return self.is_valid


def _check_mapping_ids(
    report: ValidationReport, mapping: dict, path: str, id_field: str = "id"
) -> None:
    for key, value in mapping.items():
        embedded_id = getattr(value, id_field)
        if key != embedded_id:
            report.add("key_id_mismatch", f"{path}.{key}", f"mapping key {key!r} must equal embedded id {embedded_id!r}")


def _check_unique_ids(report: ValidationReport, values: Iterable, path: str) -> None:
    counts = Counter(value.id for value in values)
    for identifier, count in counts.items():
        if count > 1:
            report.add("duplicate_id", path, f"id {identifier!r} occurs {count} times")


def validate_location_package(location: LocationPackage) -> ValidationReport:
    """Validate internal references and navigability of a location package."""
    report = ValidationReport()
    room_ids = set(location.rooms)
    object_ids = set(location.searchable_objects)
    slot_ids = set(location.evidence_slots)
    item_ids = set(location.items)
    door_ids = {door.id for door in location.doors}
    weapon_ids = set(location.potential_weapons)

    _check_mapping_ids(report, location.rooms, "rooms")
    _check_mapping_ids(report, location.searchable_objects, "searchable_objects")
    _check_mapping_ids(report, location.evidence_slots, "evidence_slots")
    _check_mapping_ids(report, location.potential_weapons, "potential_weapons")
    _check_mapping_ids(report, location.items, "items")
    _check_unique_ids(report, location.doors, "doors")
    _check_unique_ids(report, location.events, "events")
    _check_unique_ids(report, location.murder_opportunity_rules, "murder_opportunity_rules")

    if location.assembly_room_id not in room_ids:
        report.add("unknown_room", "assembly_room_id", "assembly room must name a defined room")
    for room_id, room in location.rooms.items():
        for object_id in room.searchable_object_ids:
            if object_id not in object_ids:
                report.add("unknown_object", f"rooms.{room_id}.searchable_object_ids", f"unknown searchable object {object_id!r}")

    adjacency: dict[str, set[str]] = defaultdict(set)
    for index, door in enumerate(location.doors):
        path = f"doors[{index}]"
        if door.room_a_id not in room_ids or door.room_b_id not in room_ids:
            report.add("unknown_room", path, "door endpoints must both name defined rooms")
        elif door.room_a_id == door.room_b_id:
            report.add("invalid_door", path, "a door cannot connect a room to itself")
        else:
            adjacency[door.room_a_id].add(door.room_b_id)
            if not door.one_way:
                adjacency[door.room_b_id].add(door.room_a_id)
        if door.key_item_id and door.key_item_id not in item_ids:
            report.add("unknown_item", f"{path}.key_item_id", f"unknown key item {door.key_item_id!r}")

    if location.assembly_room_id in room_ids:
        seen = {location.assembly_room_id}
        queue = deque([location.assembly_room_id])
        while queue:
            current = queue.popleft()
            for neighbour in adjacency[current] - seen:
                seen.add(neighbour)
                queue.append(neighbour)
        missing = sorted(room_ids - seen)
        if missing:
            report.add("disconnected_map", "doors", f"rooms unreachable from assembly room: {', '.join(missing)}")

    for object_id, searchable in location.searchable_objects.items():
        if searchable.room_id not in room_ids:
            report.add("unknown_room", f"searchable_objects.{object_id}.room_id", "searchable object room must exist")
        for slot_id in searchable.evidence_slot_ids:
            if slot_id not in slot_ids:
                report.add("unknown_slot", f"searchable_objects.{object_id}.evidence_slot_ids", f"unknown evidence slot {slot_id!r}")
        if searchable.requires_item_id and searchable.requires_item_id not in item_ids:
            report.add("unknown_item", f"searchable_objects.{object_id}.requires_item_id", "required item must exist")

    for slot_id, slot in location.evidence_slots.items():
        if slot.room_id not in room_ids:
            report.add("unknown_room", f"evidence_slots.{slot_id}.room_id", "evidence slot room must exist")
        if slot.object_id not in object_ids:
            report.add("unknown_object", f"evidence_slots.{slot_id}.object_id", "evidence slot object must exist")
        elif location.searchable_objects[slot.object_id].room_id != slot.room_id:
            report.add("slot_room_mismatch", f"evidence_slots.{slot_id}", "slot and containing object must be in the same room")

    for weapon_id, weapon in location.potential_weapons.items():
        if weapon.room_id not in room_ids or weapon.object_id not in object_ids:
            report.add("invalid_weapon_reference", f"potential_weapons.{weapon_id}", "weapon room and object must exist")
        elif location.searchable_objects[weapon.object_id].room_id != weapon.room_id:
            report.add("weapon_room_mismatch", f"potential_weapons.{weapon_id}", "weapon and containing object must share a room")

    for item_id, item in location.items.items():
        if item.initial_slot_id and item.initial_slot_id not in slot_ids:
            report.add("unknown_slot", f"items.{item_id}.initial_slot_id", "item initial slot must exist")
        for object_id in item.access_object_ids:
            if object_id not in object_ids:
                report.add("unknown_object", f"items.{item_id}.access_object_ids", f"unknown object {object_id!r}")
        for door_id in item.access_door_ids:
            if door_id not in door_ids:
                report.add("unknown_door", f"items.{item_id}.access_door_ids", f"unknown door {door_id!r}")

    for room_id in location.body_discovery_room_ids:
        if room_id not in room_ids:
            report.add("unknown_room", "body_discovery_room_ids", f"unknown discovery room {room_id!r}")
        elif not location.rooms[room_id].body_discovery_allowed:
            report.add("invalid_discovery_room", "body_discovery_room_ids", f"room {room_id!r} is not marked body_discovery_allowed")
    for index, rule in enumerate(location.murder_opportunity_rules):
        path = f"murder_opportunity_rules[{index}]"
        for room_id in rule.room_ids:
            if room_id not in room_ids:
                report.add("unknown_room", f"{path}.room_ids", f"unknown room {room_id!r}")
        for weapon_id in rule.weapon_ids:
            if weapon_id not in weapon_ids:
                report.add("unknown_weapon", f"{path}.weapon_ids", f"unknown weapon {weapon_id!r}")
        compatible = {method for weapon_id in rule.weapon_ids if weapon_id in weapon_ids for method in location.potential_weapons[weapon_id].compatible_methods}
        for method in rule.compatible_methods:
            if method not in compatible:
                report.add("invalid_opportunity_method", f"{path}.compatible_methods", f"method {method!r} is incompatible with the rule's weapons")
    return report


def _at_location(case: CaseDefinition, character_id: str, minute: int, room_id: str) -> bool:
    """Whether a schedule or explicit canonical event places a character there."""
    overlay = case.overlays.get(character_id)
    if overlay and any(entry.start_minute <= minute < entry.end_minute and entry.room_id == room_id for entry in overlay.schedule):
        return True
    return any(event.minute == minute and event.room_id == room_id and character_id in event.actor_ids for event in case.timeline)


def _scheduled_at_location(
    case: CaseDefinition, character_id: str, minute: int, room_id: str
) -> bool:
    overlay = case.overlays.get(character_id)
    return bool(
        overlay
        and any(
            entry.start_minute <= minute < entry.end_minute
            and entry.room_id == room_id
            for entry in overlay.schedule
        )
    )


def _prerequisite_cycle(evidence: dict) -> tuple[str, ...]:
    """Return one deterministic evidence prerequisite cycle, if present."""

    graph = {
        evidence_id: tuple(
            prerequisite_id
            for prerequisite_id in item.prerequisite_evidence_ids
            if prerequisite_id in evidence
        )
        for evidence_id, item in evidence.items()
    }
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(evidence_id: str) -> tuple[str, ...]:
        state[evidence_id] = 1
        path.append(evidence_id)
        for prerequisite_id in graph[evidence_id]:
            if state.get(prerequisite_id, 0) == 0:
                cycle = visit(prerequisite_id)
                if cycle:
                    return cycle
            elif state.get(prerequisite_id) == 1:
                start = path.index(prerequisite_id)
                return tuple(path[start:] + [prerequisite_id])
        path.pop()
        state[evidence_id] = 2
        return ()

    for evidence_id in sorted(graph):
        if state.get(evidence_id, 0) == 0:
            cycle = visit(evidence_id)
            if cycle:
                return cycle
    return ()


def _is_player_resolvable_discovery_route(
    case: CaseDefinition,
    location: LocationPackage,
    discovery_route: str,
) -> bool:
    """Whether the current player action model can execute a discovery route."""

    try:
        route_kind, target_id = discovery_route.split(":", 1)
    except ValueError:
        return False
    if route_kind == "search":
        return target_id in location.searchable_objects
    if route_kind == "interview":
        return (
            target_id in case.character_ids
            and target_id != case.murder.victim_id
        )
    if route_kind == "examine":
        return target_id == "body"
    return False


def validate_case(case: CaseDefinition, location: LocationPackage) -> ValidationReport:
    """Validate a case against a location, accumulating every detected issue."""
    report = validate_location_package(location)
    cast = set(case.character_ids)
    rooms = set(location.rooms)
    facts = set(case.facts)
    evidence_ids = set(case.evidence)
    slots = set(location.evidence_slots)
    slot_occupancy: Counter[str] = Counter()

    if case.location_package_id != location.id:
        report.add("location_mismatch", "location_package_id", f"case names {case.location_package_id!r}, validator received {location.id!r}")
    if case.initial_player_room_id not in rooms:
        report.add("unknown_room", "initial_player_room_id", "player start room must exist")
    _check_mapping_ids(report, case.facts, "facts")
    _check_mapping_ids(report, case.overlays, "overlays", "character_id")
    _check_mapping_ids(report, case.evidence, "evidence")
    _check_unique_ids(report, case.timeline, "timeline")

    if set(case.overlays) != cast:
        report.add("overlay_cast_mismatch", "overlays", "overlays must exist for exactly every character in character_ids")
    if case.murder.victim_id not in cast or case.murder.murderer_id not in cast or case.murder.victim_id == case.murder.murderer_id:
        report.add("invalid_murder_roles", "murder", "victim and murderer must be distinct cast members")
    role_counts = Counter(overlay.role for overlay in case.overlays.values())
    if role_counts[CharacterRole.VICTIM] != 1 or role_counts[CharacterRole.MURDERER] != 1 or role_counts[CharacterRole.INNOCENT] != 6:
        report.add("invalid_role_counts", "overlays", "cast must contain exactly one victim, one murderer, and six innocents")
    if case.murder.victim_id in case.overlays and case.overlays[case.murder.victim_id].role != CharacterRole.VICTIM:
        report.add("victim_role_mismatch", "murder.victim_id", "murder victim must have the victim role")
    if case.murder.murderer_id in case.overlays and case.overlays[case.murder.murderer_id].role != CharacterRole.MURDERER:
        report.add("murderer_role_mismatch", "murder.murderer_id", "murderer must have the murderer role")

    for fact_id, fact in case.facts.items():
        for character_id in fact.related_character_ids:
            if character_id not in cast:
                report.add("unknown_character", f"facts.{fact_id}.related_character_ids", f"unknown character {character_id!r}")
        for evidence_id in fact.related_evidence_ids:
            if evidence_id not in evidence_ids:
                report.add("unknown_evidence", f"facts.{fact_id}.related_evidence_ids", f"unknown evidence {evidence_id!r}")

    for index, event in enumerate(case.timeline):
        path = f"timeline[{index}]"
        if event.room_id not in rooms:
            report.add("unknown_room", f"{path}.room_id", "timeline room must exist")
        for character_id in (*event.actor_ids, *event.observed_by):
            if character_id not in cast:
                report.add("unknown_character", path, f"unknown character {character_id!r}")
        for fact_id in event.fact_ids:
            if fact_id not in facts:
                report.add("unknown_fact", f"{path}.fact_ids", f"unknown fact {fact_id!r}")
    if list(case.timeline) != sorted(case.timeline, key=lambda event: event.minute):
        report.add("timeline_not_sorted", "timeline", "timeline events must be ordered by minute")

    for character_id, overlay in case.overlays.items():
        path = f"overlays.{character_id}"
        if overlay.character_id != character_id:
            report.add("key_id_mismatch", path, "overlay key must equal character_id")
        if overlay.character_id not in cast:
            report.add("unknown_character", f"{path}.character_id", "overlay character must be in the cast")
        if overlay.starting_room_id not in rooms:
            report.add("unknown_room", f"{path}.starting_room_id", "starting room must exist")
        if not overlay.private_motive.strip():
            report.add("missing_plausible_motive", f"{path}.private_motive", "every suspect needs a plausible private motive")
        if overlay.role != CharacterRole.VICTIM and not overlay.secrets:
            report.add("missing_suspect_secret", f"{path}.secrets", "every living suspect needs at least one private secret")
        ordered = sorted(overlay.schedule, key=lambda entry: entry.start_minute)
        for schedule_index, entry in enumerate(ordered):
            schedule_path = f"{path}.schedule[{schedule_index}]"
            if entry.end_minute <= entry.start_minute:
                report.add("invalid_schedule_range", schedule_path, "schedule end_minute must be after start_minute")
            if entry.room_id not in rooms:
                report.add("unknown_room", f"{schedule_path}.room_id", "schedule room must exist")
            if schedule_index and entry.start_minute < ordered[schedule_index - 1].end_minute:
                report.add("overlapping_schedule", schedule_path, "schedule entries for one character may not overlap")
            for witness_id in entry.witnessed_by:
                if witness_id not in cast or witness_id == character_id:
                    report.add("invalid_witness", f"{schedule_path}.witnessed_by", "witness must be another cast member")
        for observation_index, observation in enumerate(overlay.observations):
            observation_path = f"{path}.observations[{observation_index}]"
            if observation.room_id not in rooms:
                report.add("unknown_room", f"{observation_path}.room_id", "observation room must exist")
            for fact_id in observation.fact_ids:
                if fact_id not in facts:
                    report.add("unknown_fact", f"{observation_path}.fact_ids", f"unknown fact {fact_id!r}")
            event_support = any(event.minute == observation.minute and event.room_id == observation.room_id and (character_id in event.actor_ids or character_id in event.observed_by) for event in case.timeline)
            private_knowledge = any(
                case.facts[fact_id].category.value == "secret"
                and character_id in case.facts[fact_id].related_character_ids
                for fact_id in observation.fact_ids
                if fact_id in facts
            )
            if not _at_location(case, character_id, observation.minute, observation.room_id) and not event_support and not private_knowledge:
                report.add("implausible_observation", observation_path, "observation needs co-location, an explicitly observed event, or a fact tied to the observer")
        for evidence_id in overlay.supporting_evidence_ids:
            if evidence_id not in evidence_ids:
                report.add("unknown_evidence", f"{path}.supporting_evidence_ids", f"unknown evidence {evidence_id!r}")
        for fact_id in overlay.hides_fact_ids:
            if fact_id not in facts:
                report.add("unknown_fact", f"{path}.hides_fact_ids", f"unknown fact {fact_id!r}")
        for lie in overlay.lies:
            for fact_id in lie.contradicts_fact_ids:
                if fact_id not in facts:
                    report.add("unknown_fact", f"{path}.lies.{lie.id}", f"unknown fact {fact_id!r}")
        for relationship in overlay.relationships:
            if relationship.target_character_id not in cast or relationship.target_character_id == character_id:
                report.add("invalid_relationship", f"{path}.relationships", "relationship target must be another cast member")
        for target_id in overlay.initial_suspicions:
            if target_id not in cast or target_id == character_id:
                report.add("invalid_suspicion_target", f"{path}.initial_suspicions", "suspicion target must be another cast member")

    for evidence_id, evidence in case.evidence.items():
        path = f"evidence.{evidence_id}"
        if not evidence.fact_ids:
            report.add("evidence_without_facts", f"{path}.fact_ids", "evidence must support at least one defined fact")
        if evidence.initial_slot_id and evidence.initial_slot_id not in slots:
            report.add("unknown_slot", f"{path}.initial_slot_id", "evidence initial slot must exist")
        elif evidence.initial_slot_id:
            slot_occupancy[evidence.initial_slot_id] += 1
            object_id = location.evidence_slots[evidence.initial_slot_id].object_id
            search_routes = {
                route
                for route in evidence.discoverable_via
                if route.startswith("search:")
            }
            expected_search_route = f"search:{object_id}"
            if search_routes != {expected_search_route}:
                report.add(
                    "slot_discovery_route_mismatch",
                    f"{path}.discoverable_via",
                    "slotted evidence may only use the containing object's search route",
                )
        for fact_id in evidence.fact_ids:
            if fact_id not in facts:
                report.add("unknown_fact", f"{path}.fact_ids", f"unknown fact {fact_id!r}")
        for character_id in (*evidence.implicates_character_ids, *evidence.exonerates_character_ids):
            if character_id not in cast:
                report.add("unknown_character", path, f"unknown character {character_id!r}")
        if evidence.is_red_herring and not evidence.red_herring_explanation.strip():
            report.add("missing_red_herring_explanation", path, "red-herring evidence needs an explanation")
        for prerequisite_id in evidence.prerequisite_evidence_ids:
            if prerequisite_id not in evidence_ids or prerequisite_id == evidence_id:
                report.add("invalid_evidence_prerequisite", f"{path}.prerequisite_evidence_ids", "prerequisite must be a different defined evidence item")
        for discovery_route in evidence.discoverable_via:
            if not _is_player_resolvable_discovery_route(
                case, location, discovery_route
            ):
                report.add("invalid_discovery_route", f"{path}.discoverable_via", f"unresolvable route {discovery_route!r}")

    prerequisite_cycle = _prerequisite_cycle(case.evidence)
    if prerequisite_cycle:
        report.add(
            "cyclic_evidence_prerequisite",
            "evidence",
            f"evidence prerequisites form a cycle: {' -> '.join(prerequisite_cycle)}",
        )

    for slot_id, occupancy in slot_occupancy.items():
        capacity = location.evidence_slots[slot_id].capacity
        if occupancy > capacity:
            report.add(
                "slot_over_capacity",
                f"evidence_slots.{slot_id}",
                f"slot holds {occupancy} evidence items but capacity is {capacity}",
            )

    murder = case.murder
    if murder.room_id not in rooms:
        report.add("unknown_room", "murder.room_id", "murder room must exist")
    if murder.weapon_id not in location.potential_weapons:
        report.add("unknown_weapon", "murder.weapon_id", "murder weapon must be a location weapon")
    elif murder.method not in location.potential_weapons[murder.weapon_id].compatible_methods:
        report.add("method_weapon_mismatch", "murder", "murder method must be compatible with murder weapon")
    for field_name in ("means", "motive", "opportunity"):
        if not getattr(murder, field_name).strip():
            report.add("missing_murder_explanation", f"murder.{field_name}", f"murder {field_name} must be specified")
    required_categories = {"means", "motive", "opportunity"}
    represented_categories = {
        fact.category.value
        for fact in case.facts.values()
        if murder.murderer_id in fact.related_character_ids
    }
    for category in required_categories - represented_categories:
        report.add("unreferenced_murder_element", "facts", f"murderer needs a {category} fact to ground the murder narrative")
    matching_rules = [
        rule for rule in location.murder_opportunity_rules
        if murder.room_id in rule.room_ids
        and murder.weapon_id in rule.weapon_ids
        and murder.method in rule.compatible_methods
    ]
    if not matching_rules:
        report.add("invalid_murder_opportunity", "murder", "murder room, weapon, and method must satisfy a location opportunity rule")
    murder_events = [event for event in case.timeline if event.minute == murder.minute and event.room_id == murder.room_id and event.event_type.value == "murder"]
    if not murder_events or not any({murder.murderer_id, murder.victim_id} <= set(event.actor_ids) for event in murder_events):
        report.add("infeasible_murder_colocation", "murder", "a murder timeline event must place killer and victim together at the murder minute")
    for character_id, role_name in (
        (murder.murderer_id, "murderer"),
        (murder.victim_id, "victim"),
    ):
        if not _scheduled_at_location(case, character_id, murder.minute, murder.room_id):
            report.add(
                "infeasible_murder_schedule",
                f"overlays.{character_id}.schedule",
                f"the {role_name} schedule must place them in the murder room at the murder minute",
            )

    opening = case.opening
    survivors = cast - {murder.victim_id}
    if opening.discovery_minute <= murder.minute:
        report.add(
            "invalid_murder_discovery_order",
            "opening.discovery_minute",
            "body discovery must occur after the murder",
        )
    if case.investigation_start_minute < opening.discovery_minute:
        report.add(
            "invalid_discovery_investigation_order",
            "investigation_start_minute",
            "the investigation cannot start before the body is discovered",
        )
    if opening.discoverer_id not in survivors:
        report.add("invalid_discoverer", "opening.discoverer_id", "discoverer must be a living cast member")
    if opening.body_room_id != murder.room_id or opening.body_room_id not in set(location.body_discovery_room_ids):
        report.add("invalid_body_room", "opening.body_room_id", "body room must be the murder room and allowed for discovery")
    if opening.assembly_room_id != location.assembly_room_id:
        report.add("invalid_assembly_room", "opening.assembly_room_id", "opening assembly room must match location assembly room")
    expected_reactions = survivors - {opening.discoverer_id}
    if set(opening.initial_reactions) != expected_reactions:
        report.add(
            "opening_reaction_mismatch",
            "opening.initial_reactions",
            "initial reactions must cover each survivor except the discoverer, whose observations form their statement",
        )
    if not opening.discoverer_observations:
        report.add(
            "missing_discoverer_statement",
            "opening.discoverer_observations",
            "the discoverer must provide at least one engine-authored observation",
        )
    if set(opening.post_meeting_room_ids) != survivors:
        report.add("opening_survivor_mismatch", "opening.post_meeting_room_ids", "post-meeting rooms must cover exactly the survivors")
    for room_id in opening.post_meeting_room_ids.values():
        if room_id not in rooms:
            report.add("unknown_room", "opening.post_meeting_room_ids", f"unknown room {room_id!r}")
    if (
        opening.discoverer_id in survivors
        and opening.body_room_id in rooms
        and not _scheduled_at_location(
            case,
            opening.discoverer_id,
            opening.discovery_minute,
            opening.body_room_id,
        )
    ):
        report.add(
            "infeasible_discoverer_schedule",
            f"overlays.{opening.discoverer_id}.schedule",
            "the discoverer schedule must place them with the body at discovery time",
        )

    solution = case.solution
    if solution.culprit_id != murder.murderer_id:
        report.add("solution_culprit_mismatch", "solution.culprit_id", "solution culprit must be the murderer")
    for axis_name, values in (
        ("method", solution.method_evidence_ids),
        ("motive", solution.motive_evidence_ids),
        ("opportunity", solution.opportunity_evidence_ids),
        ("timeline", solution.timeline_fact_ids),
    ):
        if not values:
            report.add(
                "missing_solution_axis",
                f"solution.{axis_name}",
                f"solution {axis_name} support must not be empty",
            )
    solution_evidence = set(solution.method_evidence_ids) | set(solution.motive_evidence_ids) | set(solution.opportunity_evidence_ids)
    for evidence_id in solution_evidence:
        if evidence_id not in evidence_ids:
            report.add("unknown_solution_evidence", "solution", f"unknown evidence {evidence_id!r}")
        elif not any(
            _is_player_resolvable_discovery_route(case, location, route)
            for route in case.evidence[evidence_id].discoverable_via
        ):
            report.add(
                "undiscoverable_solution_evidence",
                f"evidence.{evidence_id}.discoverable_via",
                "solution evidence must have at least one player discovery route",
            )
    reported_unreachable_prerequisites: set[str] = set()
    for solution_evidence_id in solution_evidence:
        pending = list(
            case.evidence.get(solution_evidence_id).prerequisite_evidence_ids
            if solution_evidence_id in case.evidence
            else ()
        )
        visited: set[str] = set()
        while pending:
            prerequisite_id = pending.pop()
            if prerequisite_id in visited:
                continue
            visited.add(prerequisite_id)
            prerequisite = case.evidence.get(prerequisite_id)
            if prerequisite is None:
                continue
            if not any(
                _is_player_resolvable_discovery_route(case, location, route)
                for route in prerequisite.discoverable_via
            ) and prerequisite_id not in reported_unreachable_prerequisites:
                report.add(
                    "undiscoverable_solution_prerequisite",
                    f"evidence.{prerequisite_id}.discoverable_via",
                    f"solution evidence depends on unreachable prerequisite {prerequisite_id!r}",
                )
                reported_unreachable_prerequisites.add(prerequisite_id)
            pending.extend(prerequisite.prerequisite_evidence_ids)
    for fact_id in solution.timeline_fact_ids:
        if fact_id not in facts:
            report.add("unknown_solution_fact", "solution.timeline_fact_ids", f"unknown fact {fact_id!r}")
        elif case.facts[fact_id].category.value not in {
            "timeline",
            "opportunity",
            "alibi",
        }:
            report.add(
                "invalid_solution_timeline_fact",
                "solution.timeline_fact_ids",
                f"fact {fact_id!r} is not timeline, opportunity, or alibi evidence",
            )
    for axis, expected_categories, axis_evidence_ids in (
        ("method", {"means"}, solution.method_evidence_ids),
        ("motive", {"motive"}, solution.motive_evidence_ids),
        ("opportunity", {"opportunity", "timeline"}, solution.opportunity_evidence_ids),
    ):
        for evidence_id in axis_evidence_ids:
            evidence = case.evidence.get(evidence_id)
            if evidence is None:
                continue
            categories = {
                case.facts[fact_id].category.value
                for fact_id in evidence.fact_ids
                if fact_id in case.facts
            }
            if not (expected_categories & categories):
                report.add(
                    "solution_evidence_axis_mismatch",
                    f"solution.{axis}_evidence_ids",
                    f"evidence {evidence_id!r} does not support one of {sorted(expected_categories)!r}",
                )
                continue
            reciprocal_categories = {
                case.facts[fact_id].category.value
                for fact_id in evidence.fact_ids
                if fact_id in case.facts
                and evidence_id in case.facts[fact_id].related_evidence_ids
            }
            if not (expected_categories & reciprocal_categories):
                report.add(
                    "nonreciprocal_solution_link",
                    f"solution.{axis}_evidence_ids",
                    f"evidence {evidence_id!r} is not reciprocally linked from a matching fact",
                )
    groups = {case.evidence[evidence_id].redundancy_group for evidence_id in solution_evidence if evidence_id in case.evidence}
    required = solution.independent_evidence_groups_required
    if len(groups) < required:
        report.add("insufficient_independent_evidence", "solution", f"requires {required} independent groups, found {len(groups)}")
    for evidence_id in solution_evidence:
        evidence = case.evidence.get(evidence_id)
        if evidence and evidence.manipulable:
            remaining_groups = {case.evidence[other_id].redundancy_group for other_id in solution_evidence - {evidence_id} if other_id in case.evidence}
            if len(remaining_groups) < required:
                report.add("manipulable_clue_breaks_solution", f"evidence.{evidence_id}", "removing this manipulable solution clue leaves too few independent groups")

    implication_groups: dict[str, set[str]] = defaultdict(set)
    for evidence in case.evidence.values():
        if evidence.is_red_herring:
            continue
        for character_id in evidence.implicates_character_ids:
            implication_groups[character_id].add(evidence.redundancy_group)
    culprit_score = len(implication_groups[murder.murderer_id])
    rival_score = max(
        (len(implication_groups[character_id]) for character_id in cast - {murder.murderer_id}),
        default=0,
    )
    if culprit_score < required or culprit_score <= rival_score:
        report.add(
            "culprit_not_uniquely_supported",
            "evidence",
            f"culprit has {culprit_score} independent implication groups versus rival best {rival_score}; expected a unique score of at least {required}",
        )
    return report
