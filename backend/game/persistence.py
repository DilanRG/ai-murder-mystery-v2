"""Validated, local save files for the deterministic game engine.

Save files deliberately contain only mutable runtime state plus stable authored
content identifiers.  They never embed a :class:`CaseDefinition` or location
package, which keeps canonical truth out of portable/client-facing payloads and
means authored updates are detected when a save is restored.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from pydantic import ValidationError

from game.accusation import evaluate_accusation_support
from game.models import (
    CaseDefinition,
    EvidenceCondition,
    GamePhase,
    LocationPackage,
    StrictModel,
    WorldRuntimeState,
)
from game.recipes import (
    CaseRecipeSelection,
    RecipeValidationError,
    case_content_fingerprint,
    resolve_case_recipe,
)


SAVE_SCHEMA_VERSION = 1
PLAYER_ID = "player"


class SaveValidationError(ValueError):
    """A save was malformed, incompatible, or violates runtime invariants."""


class SaveEnvelope(StrictModel):
    """Portable save document with no authored ground truth embedded in it."""

    schema_version: Literal[1] = SAVE_SCHEMA_VERSION
    case_id: str
    location_id: str
    case_recipe: CaseRecipeSelection | None = None
    runtime: WorldRuntimeState


def _fail(message: str) -> None:
    raise SaveValidationError(message)


def _require_exact_keys(label: str, actual: object, expected: set[str]) -> None:
    if not isinstance(actual, Mapping) or set(actual) != expected:
        _fail(f"{label} keys do not match the authored content")


def _require_subset(label: str, values: object, permitted: set[str]) -> None:
    value_set = set(values) if isinstance(values, (set, list, tuple)) else set()
    if not isinstance(values, (set, list, tuple)) or not value_set <= permitted:
        _fail(f"{label} references an unknown authored ID")


def validate_runtime_state(
    runtime: WorldRuntimeState,
    case: CaseDefinition,
    location: LocationPackage,
) -> None:
    """Reject a runtime snapshot that cannot have come from this engine.

    This is intentionally stricter than Pydantic's shape validation.  In
    particular, every runtime map is a one-to-one projection of its authored
    source, so a hand-edited save cannot inject or remove an entity.
    """

    if runtime.schema_version != SAVE_SCHEMA_VERSION:
        _fail("unsupported runtime schema version")
    if runtime.case_id != case.id or runtime.seed != case.seed:
        _fail("runtime does not belong to the requested authored case")

    cast_ids = set(case.character_ids)
    room_ids = set(location.rooms)
    evidence_ids = set(case.evidence)
    door_ids = {door.id for door in location.doors}
    object_ids = set(location.searchable_objects)
    item_ids = set(location.items)
    weapon_ids = set(location.potential_weapons)
    slot_ids = set(location.evidence_slots)
    fact_ids = set(case.facts)

    _require_exact_keys("characters", runtime.characters, cast_ids)
    _require_exact_keys("evidence", runtime.evidence, evidence_ids)
    _require_exact_keys("doors", runtime.doors, door_ids)
    _require_exact_keys("searchable objects", runtime.searchable_objects, object_ids)
    _require_exact_keys("items", runtime.items, item_ids)
    _require_exact_keys("weapons", runtime.weapons, weapon_ids)

    if runtime.player_room_id not in room_ids:
        _fail("player room is not in the selected location")
    expected_minute = case.investigation_start_minute + runtime.turn * case.turn_minutes
    if runtime.in_game_minute != expected_minute:
        _fail("runtime clock is inconsistent with its turn count")
    if runtime.turn > case.max_turns:
        _fail("runtime turn count exceeds the case limit")

    victim_id = case.murder.victim_id
    for character_id, state in runtime.characters.items():
        if state.character_id != character_id or state.current_room_id not in room_ids:
            _fail("character runtime state has an invalid identity or room")
        if character_id == victim_id and state.alive:
            _fail("the authored victim cannot be alive in a saved investigation")
        if character_id != victim_id and not state.alive:
            _fail("an authored survivor cannot be dead in this game mode")
        _require_subset(f"{character_id} known facts", state.known_fact_ids, fact_ids)
        _require_subset(f"{character_id} known evidence", state.known_evidence_ids, evidence_ids)
        _require_subset(f"{character_id} inventory", state.inventory_item_ids, item_ids)
        for subject_id, belief in state.beliefs.items():
            if subject_id not in cast_ids or belief.subject_character_id != subject_id:
                _fail("belief state has an unknown subject")
            _require_subset("belief reasons", belief.reason_fact_ids, fact_ids)
        for memory in state.conversation_memory:
            if memory.speaker_id not in cast_ids:
                _fail("conversation memory has an unknown speaker")
            _require_subset("conversation listeners", memory.listener_ids, cast_ids | {PLAYER_ID})
            _require_subset("conversation facts", memory.referenced_fact_ids, fact_ids)

    for evidence_id, state in runtime.evidence.items():
        if state.evidence_id != evidence_id:
            _fail("evidence runtime state has a mismatched ID")
        if state.current_slot_id is not None and state.current_slot_id not in slot_ids:
            _fail("evidence references an unknown location slot")
        if state.holder_character_id is not None and state.holder_character_id not in cast_ids | {PLAYER_ID}:
            _fail("evidence has an unknown holder")
        if state.current_slot_id is not None and state.holder_character_id is not None:
            _fail("evidence cannot be both slotted and held")
        _require_subset("evidence discoverers", state.discovered_by_character_ids, cast_ids | {PLAYER_ID})
        if state.discovered_by_player != (PLAYER_ID in state.discovered_by_character_ids):
            _fail("player discovery flags are inconsistent")
        if state.discovered_by_player != (evidence_id in runtime.player_knowledge.discovered_evidence_ids):
            _fail("player evidence knowledge is inconsistent")
        if state.discovered_by_player and state.discovered_turn is None:
            _fail("player-discovered evidence has no discovery turn")
        if state.discovered_turn is not None and state.discovered_turn > runtime.turn:
            _fail("evidence discovery occurs after the saved turn")
        if state.condition == EvidenceCondition.COLLECTED and not state.discovered_by_player:
            _fail("collected evidence must have been discovered by the player")

    for door_id, state in runtime.doors.items():
        if state.door_id != door_id:
            _fail("door runtime state has a mismatched ID")
    for object_id, state in runtime.searchable_objects.items():
        if state.object_id != object_id:
            _fail("searchable object runtime state has a mismatched ID")
    for item_id, state in runtime.items.items():
        if state.item_id != item_id:
            _fail("item runtime state has a mismatched ID")
        if state.current_slot_id is not None and state.current_slot_id not in slot_ids:
            _fail("item references an unknown location slot")
        if state.holder_character_id is not None and state.holder_character_id not in cast_ids | {PLAYER_ID}:
            _fail("item has an unknown holder")
        if state.current_slot_id is not None and state.holder_character_id is not None:
            _fail("item cannot be both slotted and held")
        if state.holder_character_id in cast_ids and item_id not in runtime.characters[state.holder_character_id].inventory_item_ids:
            _fail("character-held item is missing from that character inventory")
    for weapon_id, state in runtime.weapons.items():
        if state.weapon_id != weapon_id or state.current_room_id not in room_ids:
            _fail("weapon runtime state has an invalid identity or room")
        if state.holder_character_id is not None and state.holder_character_id not in cast_ids | {PLAYER_ID}:
            _fail("weapon has an unknown holder")

    knowledge = runtime.player_knowledge
    _require_subset("discovered rooms", knowledge.discovered_room_ids, room_ids)
    if runtime.phase != GamePhase.DISCOVERY and runtime.player_room_id not in knowledge.discovered_room_ids:
        _fail("the player's current investigation room must be known")
    for character_id, room_id in knowledge.observed_character_room_ids.items():
        if character_id not in cast_ids or room_id not in room_ids:
            _fail("observed character location is invalid")
    _require_subset("player facts", knowledge.known_fact_ids, fact_ids)
    _require_subset("player evidence", knowledge.discovered_evidence_ids, evidence_ids)
    _require_subset("unread items", knowledge.unread_item_ids, item_ids)

    statement_ids: set[str] = set()
    for statement in knowledge.statements:
        if statement.id in statement_ids or statement.speaker_id not in cast_ids:
            _fail("statements must have unique IDs and authored speakers")
        statement_ids.add(statement.id)
        _require_subset("statement audience", statement.audience_ids, cast_ids | {PLAYER_ID})
        _require_subset("statement facts", statement.referenced_fact_ids, fact_ids)
        if statement.turn > runtime.turn or statement.minute > runtime.in_game_minute:
            _fail("statement occurs after the saved runtime")
    for character_id, state in runtime.characters.items():
        _require_subset(f"{character_id} heard statements", state.statement_ids_heard, statement_ids)
    for entry in knowledge.timeline:
        if entry.minute is not None and entry.minute > runtime.in_game_minute:
            _fail("player timeline entry occurs after the saved runtime")
        _require_subset("timeline sources", entry.source_ids, evidence_ids | fact_ids | statement_ids)
    for contradiction in knowledge.contradictions:
        if contradiction.left_statement_id not in statement_ids or contradiction.right_statement_id not in statement_ids:
            _fail("contradiction references an unknown statement")
    event_ids: set[str] = set()
    for event in runtime.event_log:
        if event.id in event_ids or event.room_id not in room_ids:
            _fail("event log has a duplicate ID or invalid room")
        event_ids.add(event.id)
        _require_subset("event actors", event.actor_ids, cast_ids | {PLAYER_ID})
        _require_subset("event facts", event.fact_ids, fact_ids)
        _require_subset("event visibility", event.visible_to_character_ids, cast_ids | {PLAYER_ID})
        if event.turn > runtime.turn or event.minute > runtime.in_game_minute:
            _fail("event occurs after the saved runtime")

    interview = runtime.active_interview
    if interview is not None:
        if runtime.phase != GamePhase.INVESTIGATION:
            _fail("an interview may only be active during investigation")
        if interview.character_id not in cast_ids or not runtime.characters[interview.character_id].alive:
            _fail("active interview has an invalid character")
        if runtime.characters[interview.character_id].current_room_id != runtime.player_room_id:
            _fail("active interview participant is not with the player")
        if interview.started_turn > runtime.turn or not set(interview.statement_ids) <= statement_ids:
            _fail("active interview metadata is inconsistent")
    if runtime.phase == GamePhase.ENDED and interview is not None:
        _fail("a completed game cannot retain an active interview")

    result = runtime.result
    if result is not None:
        if runtime.phase != GamePhase.ENDED:
            _fail("a result requires an ended game phase")
        if result.accused_character_id not in cast_ids:
            _fail("result names an unknown accused character")
        if result.correct_culprit != (result.accused_character_id == case.solution.culprit_id):
            _fail("result culprit flag conflicts with authored solution")
        _require_subset("selected result evidence", result.selected_evidence_ids, knowledge.discovered_evidence_ids)
        _require_subset("selected result timeline facts", result.selected_timeline_fact_ids, knowledge.known_fact_ids)
        _require_subset("selected result timeline facts", result.selected_timeline_fact_ids, set(case.solution.timeline_fact_ids))
        expected_supports = evaluate_accusation_support(
            case,
            known_fact_ids=knowledge.known_fact_ids,
            selected_evidence_ids=result.selected_evidence_ids,
            method=result.submitted_method,
            motive=result.submitted_motive,
            timeline=result.submitted_timeline,
        )
        if (result.method_supported, result.motive_supported, result.timeline_supported) != expected_supports:
            _fail("result support flags conflict with selected evidence and claims")
        if result.support_score != sum(expected_supports):
            _fail("result support score conflicts with selected evidence and claims")
        if result.solved != (result.correct_culprit and result.support_score >= 2):
            _fail("result solved flag is inconsistent")

    if runtime.phase == GamePhase.DISCOVERY:
        if runtime.turn != 0 or runtime.in_game_minute != case.investigation_start_minute:
            _fail("discovery phase must be the untouched opening state")
        if runtime.active_interview is not None or runtime.result is not None:
            _fail("discovery phase cannot have an interview or result")
    elif runtime.phase == GamePhase.INVESTIGATION and runtime.result is not None:
        _fail("investigation phase cannot contain a final result")


def validate_save_envelope(
    value: SaveEnvelope | Mapping[str, Any],
    case: CaseDefinition,
    location: LocationPackage,
) -> SaveEnvelope:
    """Parse and validate an untrusted save against the supplied authored data."""

    try:
        envelope = value if isinstance(value, SaveEnvelope) else SaveEnvelope.model_validate(value)
    except ValidationError as error:
        raise SaveValidationError("save document does not match the supported schema") from error
    if envelope.schema_version != SAVE_SCHEMA_VERSION:
        _fail("unsupported save schema version")
    if envelope.case_id != case.id or envelope.location_id != location.id:
        _fail("save references different authored content")
    if case.location_package_id != location.id:
        _fail("provided case and location are not compatible")
    if envelope.case_recipe is not None:
        selection = envelope.case_recipe
        if selection.selected_case_id != envelope.case_id:
            _fail("saved recipe selection does not match the selected case")
        if selection.content_fingerprint != case_content_fingerprint(case):
            _fail("saved recipe content fingerprint does not match authored content")
        try:
            resolved = resolve_case_recipe(selection.recipe_id, selection.seed)
        except RecipeValidationError as error:
            raise SaveValidationError("saved recipe can no longer be resolved") from error
        if resolved != selection:
            _fail("saved recipe selection is not reproducible")
    validate_runtime_state(envelope.runtime, case, location)
    return envelope


def snapshot_engine(engine: Any) -> SaveEnvelope:
    """Create a validated envelope from a ``GameEngine`` without copying truth."""

    envelope = SaveEnvelope(
        case_id=engine.case.id,
        location_id=engine.location.id,
        case_recipe=engine.recipe_selection,
        runtime=engine.runtime.model_copy(deep=True),
    )
    return validate_save_envelope(envelope, engine.case, engine.location)


def restore_engine(
    save: SaveEnvelope | Mapping[str, Any],
    case: CaseDefinition,
    location: LocationPackage,
) -> Any:
    """Recreate an engine only after the save validates against authored truth."""

    envelope = validate_save_envelope(save, case, location)
    # Local import avoids coupling the engine module to persistence at startup.
    from game.engine import GameEngine

    engine = GameEngine(case, location, recipe_selection=envelope.case_recipe)
    engine.runtime = envelope.runtime.model_copy(deep=True)
    return engine


def safe_save_path(save_root: Path | str, filename: str) -> Path:
    """Return a single JSON save path confined to a caller-configured root."""

    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        _fail("save filename must be a single file name")
    candidate_name = Path(filename)
    if candidate_name.suffix.lower() != ".json":
        _fail("save filename must end in .json")
    root = Path(save_root).resolve(strict=False)
    candidate = (root / candidate_name).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise SaveValidationError("save path escapes the configured save root") from error
    return candidate


def write_save(engine: Any, save_root: Path | str, filename: str) -> Path:
    """Atomically write a validated engine snapshot beneath ``save_root``."""

    destination = safe_save_path(save_root, filename)
    envelope = snapshot_engine(engine)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, prefix=".save-", suffix=".tmp", delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return destination


def read_save(save_root: Path | str, filename: str) -> SaveEnvelope:
    """Read only the JSON/Pydantic envelope; call ``restore_engine`` to use it."""

    source = safe_save_path(save_root, filename)
    try:
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise SaveValidationError("save file could not be read as JSON") from error
    try:
        return SaveEnvelope.model_validate(payload)
    except ValidationError as error:
        raise SaveValidationError("save document does not match the supported schema") from error


def load_engine(
    save_root: Path | str,
    filename: str,
    *,
    case_loader: Callable[[str], CaseDefinition] | None = None,
    location_loader: Callable[[str], LocationPackage] | None = None,
) -> Any:
    """Load authored IDs from a save and restore its validated engine state."""

    envelope = read_save(save_root, filename)
    if case_loader is None or location_loader is None:
        from game.content import load_case, load_location

        case_loader = case_loader or load_case
        location_loader = location_loader or load_location
    try:
        case = case_loader(envelope.case_id)
        location = location_loader(envelope.location_id)
    except (OSError, ValueError, FileNotFoundError) as error:
        raise SaveValidationError("save references unavailable authored content") from error
    return restore_engine(envelope, case, location)
