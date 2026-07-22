"""Cross-document validation for authored locations and mystery cases.

Pydantic verifies the shape of each document.  This module verifies the
relationships that only make sense once a case is paired with its location.
It deliberately returns *all* findings so content authors can fix a package in
one editing pass.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable

from game.models import CaseDefinition, CharacterRole, LocationPackage
from game.stage1_semantic import compiled_causal_chain_issues


_DIRECT_MURDER_CONFESSION = re.compile(
    r"\b(?:"
    r"(?:i|we)\s+(?:killed|murdered|poisoned|stabbed|shot|strangled)\b|"
    r"(?:i\s+am|i'm|we\s+are|we're)\s+(?:the\s+)?(?:killer|murderer)\b|"
    r"it\s+was\s+(?:me|us)\s+who\s+(?:killed|murdered|poisoned|stabbed|shot|strangled)\b"
    r")",
    re.IGNORECASE,
)
_LOCATION_EVENT_TRIGGER = re.compile(r"turn_([1-9]\d{0,3})")
SUPPORTED_LOCATION_EVENT_EFFECTS = frozenset({"atmosphere_only"})


def claim_contains_direct_murder_confession(claim: str) -> bool:
    """Detect explicit first-person murder admissions in interview-safe claims."""

    return _DIRECT_MURDER_CONFESSION.search(claim) is not None


def location_event_turn(trigger: str) -> int | None:
    """Return the strict positive turn encoded by a location-event trigger."""

    match = _LOCATION_EVENT_TRIGGER.fullmatch(trigger)
    return int(match.group(1)) if match else None


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

    for index, event in enumerate(location.events):
        path = f"events[{index}]"
        if location_event_turn(event.trigger) is None:
            report.add(
                "invalid_event_trigger",
                f"{path}.trigger",
                "event trigger must use turn_N with N from 1 to 9999",
            )
        if event.engine_effect not in SUPPORTED_LOCATION_EVENT_EFFECTS:
            report.add(
                "unsupported_event_effect",
                f"{path}.engine_effect",
                "event effect is not supported by the deterministic engine",
            )

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


def _evidence_with_prerequisites(
    case: CaseDefinition,
    evidence_ids: Iterable[str],
) -> set[str]:
    """Return the evidence closure needed to establish a proposed proof route."""

    closure: set[str] = set()
    pending = list(evidence_ids)
    while pending:
        evidence_id = pending.pop()
        if evidence_id in closure or evidence_id not in case.evidence:
            continue
        closure.add(evidence_id)
        pending.extend(case.evidence[evidence_id].prerequisite_evidence_ids)
    return closure


def validate_generated_evidence_routes(
    case: CaseDefinition,
    routes: Iterable,
) -> ValidationReport:
    """Validate generated proof routes without changing legacy authored schemas.

    Each declared route must stand on its own: it covers every accusation axis
    and one timeline fact, uniquely points to the culprit, and shares neither
    evidence (including prerequisites) nor a redundancy group with another
    declared route.
    """

    report = ValidationReport()
    route_closures: list[set[str]] = []
    route_groups: list[set[str]] = []
    solution = case.solution
    allowed_by_axis = {
        "method": set(solution.method_evidence_ids),
        "motive": set(solution.motive_evidence_ids),
        "opportunity": set(solution.opportunity_evidence_ids),
    }
    allowed_timeline_facts = set(solution.timeline_fact_ids)
    cast = set(case.character_ids)
    culprit_id = case.murder.murderer_id
    route_ids: set[str] = set()

    for index, route in enumerate(routes):
        path = f"solution.evidence_routes[{index}]"
        if route.id in route_ids:
            report.add(
                "duplicate_evidence_route_id",
                f"{path}.id",
                f"duplicate evidence route id {route.id!r}",
            )
        route_ids.add(route.id)
        axis_sets = (
            set(route.method_evidence_ids),
            set(route.motive_evidence_ids),
            set(route.opportunity_evidence_ids),
        )
        if any(
            len(values) != len(set(values))
            for values in (
                route.method_evidence_ids,
                route.motive_evidence_ids,
                route.opportunity_evidence_ids,
                route.timeline_fact_ids,
            )
        ):
            report.add(
                "duplicate_route_reference",
                path,
                "a proof route cannot repeat evidence or timeline references",
            )
        if any(
            axis_sets[left] & axis_sets[right]
            for left, right in ((0, 1), (0, 2), (1, 2))
        ):
            report.add(
                "route_axis_evidence_overlap",
                path,
                "one evidence item cannot stand in for multiple accusation axes within a route",
            )
        direct_ids = {
            *route.method_evidence_ids,
            *route.motive_evidence_ids,
            *route.opportunity_evidence_ids,
        }
        for axis, evidence_ids in (
            ("method", route.method_evidence_ids),
            ("motive", route.motive_evidence_ids),
            ("opportunity", route.opportunity_evidence_ids),
        ):
            unexpected = set(evidence_ids) - allowed_by_axis[axis]
            if unexpected:
                report.add(
                    "route_evidence_not_in_solution_axis",
                    f"{path}.{axis}_evidence_ids",
                    f"route {axis} evidence is not part of the declared solution axis: {', '.join(sorted(unexpected))}",
                )
        unexpected_facts = set(route.timeline_fact_ids) - allowed_timeline_facts
        if unexpected_facts:
            report.add(
                "route_timeline_not_in_solution",
                f"{path}.timeline_fact_ids",
                f"route timeline facts are not part of the declared solution: {', '.join(sorted(unexpected_facts))}",
            )

        closure = _evidence_with_prerequisites(case, direct_ids)
        route_closures.append(closure)
        groups = {
            case.evidence[evidence_id].redundancy_group
            for evidence_id in closure
        }
        route_groups.append(groups)
        supported_facts = {
            fact_id
            for evidence_id in closure
            for fact_id in case.evidence[evidence_id].fact_ids
        }
        if not set(route.timeline_fact_ids) <= supported_facts:
            report.add(
                "route_timeline_not_supported",
                f"{path}.timeline_fact_ids",
                "route timeline facts must be supported by that route's evidence or prerequisites",
            )

        implication_groups: dict[str, set[str]] = defaultdict(set)
        culprit_exoneration_groups: set[str] = set()
        for evidence_id in closure:
            evidence = case.evidence[evidence_id]
            if evidence.is_red_herring:
                report.add(
                    "red_herring_in_evidence_route",
                    path,
                    f"proof route contains red herring {evidence_id!r}",
                )
                continue
            for character_id in evidence.implicates_character_ids:
                implication_groups[character_id].add(evidence.redundancy_group)
            if culprit_id in evidence.exonerates_character_ids:
                culprit_exoneration_groups.add(evidence.redundancy_group)
        if culprit_exoneration_groups:
            report.add(
                "evidence_route_exonerates_culprit",
                path,
                "a canonical proof route cannot contain evidence that exonerates "
                f"the culprit (groups: {', '.join(sorted(culprit_exoneration_groups))})",
            )
        culprit_score = len(implication_groups[culprit_id])
        rival_score = max(
            (len(implication_groups[character_id]) for character_id in cast - {culprit_id}),
            default=0,
        )
        if culprit_score < 2 or culprit_score <= rival_score:
            report.add(
                "route_culprit_not_uniquely_supported",
                path,
                f"route supports culprit in {culprit_score} groups versus rival best {rival_score}; at least two culprit groups are required",
            )

    if len(route_closures) < 2:
        report.add(
            "insufficient_independent_evidence_routes",
            "solution.evidence_routes",
            "generated cases require at least two independently complete evidence routes",
        )
    for index, closure in enumerate(route_closures):
        for other_index in range(index):
            overlap = closure & route_closures[other_index]
            group_overlap = route_groups[index] & route_groups[other_index]
            if overlap or group_overlap:
                details = []
                if overlap:
                    details.append(f"evidence {', '.join(sorted(overlap))}")
                if group_overlap:
                    details.append(f"groups {', '.join(sorted(group_overlap))}")
                report.add(
                    "overlapping_independent_evidence_routes",
                    f"solution.evidence_routes[{index}]",
                    f"route overlaps route {other_index} through {' and '.join(details)}",
                )
    return report


def validate_generated_private_states(case: CaseDefinition) -> ValidationReport:
    """Require every living generated NPC to begin with a real private agenda."""

    report = ValidationReport()
    signatures: dict[tuple[object, ...], str] = {}
    for character_id in case.character_ids:
        if character_id == case.murder.victim_id:
            continue
        overlay = case.overlays.get(character_id)
        if overlay is None:
            continue
        required_collections = (
            ("observations", overlay.observations),
            ("secrets", overlay.secrets),
            ("relationships", overlay.relationships),
            ("goals", overlay.goals),
            ("initial_suspicions", overlay.initial_suspicions),
        )
        for field_name, values in required_collections:
            if not values:
                report.add(
                    "incomplete_generated_private_state",
                    f"overlays.{character_id}.{field_name}",
                    f"living generated NPC {character_id!r} needs private {field_name}",
                )
        known_fact_ids = {
            fact_id
            for observation in overlay.observations
            for fact_id in observation.fact_ids
        }
        if not known_fact_ids:
            report.add(
                "generated_npc_without_private_knowledge",
                f"overlays.{character_id}.observations",
                "a living generated NPC must begin with at least one observed fact",
            )
        unsupported_hidden_facts = set(overlay.hides_fact_ids) - known_fact_ids
        if unsupported_hidden_facts:
            report.add(
                "unproven_generated_private_knowledge",
                f"overlays.{character_id}.hides_fact_ids",
                "concealed facts must be grounded in that NPC's own observations: "
                + ", ".join(sorted(unsupported_hidden_facts)),
            )
        disclosed_fact_ids = {
            *overlay.alibi_disclosed_fact_ids,
            *(
                fact_id
                for lie in overlay.lies
                for fact_id in lie.disclosed_fact_ids
            ),
        }
        unsupported_disclosures = disclosed_fact_ids - known_fact_ids
        if unsupported_disclosures:
            report.add(
                "unproven_generated_fact_disclosure",
                f"overlays.{character_id}",
                "an NPC may disclose only facts grounded in its own observations: "
                + ", ".join(sorted(unsupported_disclosures)),
            )
        for evidence_id in overlay.supporting_evidence_ids:
            evidence = case.evidence.get(evidence_id)
            if evidence is not None and not (
                set(evidence.fact_ids) & known_fact_ids
            ):
                report.add(
                    "unproven_generated_evidence_knowledge",
                    f"overlays.{character_id}.supporting_evidence_ids",
                    f"evidence {evidence_id!r} is not grounded in that NPC's observations",
                )
        signature = (
            overlay.private_motive,
            overlay.secrets,
            overlay.goals,
            tuple(
                (
                    relationship.target_character_id,
                    relationship.private_summary,
                    relationship.affinity,
                )
                for relationship in overlay.relationships
            ),
            tuple(sorted(overlay.initial_suspicions.items())),
            overlay.initial_emotional_state,
        )
        duplicate_of = signatures.get(signature)
        if duplicate_of is not None:
            report.add(
                "duplicate_generated_private_state",
                f"overlays.{character_id}",
                f"private agenda duplicates {duplicate_of!r}",
            )
        signatures[signature] = character_id
    return report


def validate_generated_timeline_consistency(case: CaseDefinition) -> ValidationReport:
    """Require every generated timeline participant to be physically present."""

    report = ValidationReport()
    for index, event in enumerate(case.timeline):
        for character_id in sorted({*event.actor_ids, *event.observed_by}):
            if character_id not in case.overlays:
                continue
            overlay = case.overlays[character_id]
            scheduled_here = _scheduled_at_location(
                case, character_id, event.minute, event.room_id
            )
            transition_from_here = (
                event.event_type.value in {"schedule", "observation"}
                and any(
                    entry.end_minute == event.minute
                    and entry.room_id == event.room_id
                    for entry in overlay.schedule
                )
            )
            body_remains_here = (
                character_id == case.murder.victim_id
                and event.minute >= case.murder.minute
                and event.room_id == case.murder.room_id
            )
            opening_assembly = (
                character_id != case.murder.victim_id
                and event.event_type.value == "meeting"
                and event.minute >= case.opening.discovery_minute
                and event.room_id == case.opening.assembly_room_id
            )
            if not (
                scheduled_here
                or transition_from_here
                or body_remains_here
                or opening_assembly
            ):
                report.add(
                    "inconsistent_generated_timeline_location",
                    f"timeline[{index}]",
                    f"{character_id!r} participates at minute {event.minute} in "
                    f"{event.room_id!r} but its schedule places it elsewhere",
                )
    return report


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
    _check_mapping_ids(report, case.case_means, "case_means")
    _check_mapping_ids(report, case.overlays, "overlays", "character_id")
    _check_mapping_ids(report, case.evidence, "evidence")
    _check_unique_ids(report, case.timeline, "timeline")

    for index, event in enumerate(location.events):
        trigger_turn = location_event_turn(event.trigger)
        if trigger_turn is not None and trigger_turn > case.max_turns:
            report.add(
                "unreachable_event_trigger",
                f"events[{index}].trigger",
                "event trigger occurs after the case turn limit",
            )

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
        hidden_fact_ids = set(overlay.hides_fact_ids)
        for fact_id in overlay.alibi_disclosed_fact_ids:
            if fact_id not in facts:
                report.add(
                    "unknown_fact",
                    f"{path}.alibi_disclosed_fact_ids",
                    f"unknown fact {fact_id!r}",
                )
            elif fact_id in hidden_fact_ids:
                report.add(
                    "hidden_fact_disclosure",
                    f"{path}.alibi_disclosed_fact_ids",
                    f"alibi candidate discloses hidden fact {fact_id!r}",
                )
        if (
            character_id == case.murder.murderer_id
            and claim_contains_direct_murder_confession(overlay.alibi_claim)
        ):
            report.add(
                "murderer_confession_candidate",
                f"{path}.alibi_claim",
                "murderer alibi must not directly confess to the murder",
            )
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
            for fact_id in lie.disclosed_fact_ids:
                if fact_id not in facts:
                    report.add(
                        "unknown_fact",
                        f"{path}.lies.{lie.id}.disclosed_fact_ids",
                        f"unknown fact {fact_id!r}",
                    )
                elif fact_id in hidden_fact_ids:
                    report.add(
                        "hidden_fact_disclosure",
                        f"{path}.lies.{lie.id}.disclosed_fact_ids",
                        f"authorized lie discloses hidden fact {fact_id!r}",
                    )
            if (
                character_id == case.murder.murderer_id
                and claim_contains_direct_murder_confession(lie.claim)
            ):
                report.add(
                    "murderer_confession_candidate",
                    f"{path}.lies.{lie.id}.claim",
                    "murderer authorized lie must not directly confess to the murder",
                )
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
        contradictory_characters = set(evidence.implicates_character_ids) & set(
            evidence.exonerates_character_ids
        )
        if case.solution.evidence_routes and contradictory_characters:
            report.add(
                "contradictory_evidence_character_effect",
                path,
                "evidence cannot both implicate and exonerate the same character: "
                + ", ".join(sorted(contradictory_characters)),
            )
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
    if case.stage1_contract_version == "legacy":
        if murder.weapon_id not in location.potential_weapons:
            report.add("unknown_weapon", "murder.weapon_id", "murder weapon must be a location weapon")
        elif murder.method not in location.potential_weapons[murder.weapon_id].compatible_methods:
            report.add("method_weapon_mismatch", "murder", "murder method must be compatible with murder weapon")
    elif murder.weapon_id not in case.case_means:
        report.add("unknown_case_means", "murder.weapon_id", "semantic murder must reference case-specific means")
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
    if case.stage1_contract_version == "legacy":
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
    else:
        for issue in compiled_causal_chain_issues(
            murder=murder,
            timeline=case.timeline,
            case_means=case.case_means,
            opening=case.opening,
            character_ids=case.character_ids,
            location=location,
        ):
            report.add(issue.code, issue.path.lstrip("/"), issue.message)

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
    if solution.evidence_routes:
        report.extend(
            validate_generated_evidence_routes(case, solution.evidence_routes)
        )
        report.extend(validate_generated_private_states(case))
        report.extend(validate_generated_timeline_consistency(case))
    return report
