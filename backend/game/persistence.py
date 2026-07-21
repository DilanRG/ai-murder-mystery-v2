"""Validated, local save files for the deterministic game engine.

Authored cases use stable content identifiers so updates are detected on
restore. Provider-generated cases have no authored source to reload, so their
validated immutable :class:`CaseDefinition` is embedded with a content
fingerprint. Save files remain local server-side artifacts and are never
returned by the public game-state API.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from pydantic import Field, ValidationError, model_validator

from game.accusation import evaluate_accusation_support
from game.models import (
    ActionHistoryEntry,
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
    materialize_case_recipe,
    resolve_case_recipe,
)
from game.story_director import StoryPresentationPatch, validate_story_presentation
from game.validator import location_event_turn, validate_case


SAVE_SCHEMA_VERSION = 4
PRE_LOCATION_EVENT_SAVE_SCHEMA_VERSION = 3
PRE_INTERVIEW_AGENT_SAVE_SCHEMA_VERSION = 2
LEGACY_SAVE_SCHEMA_VERSION = 1
RUNTIME_SCHEMA_VERSION = 1
MAX_ACTION_HISTORY = 1_024
PLAYER_ID = "player"


class SaveValidationError(ValueError):
    """A save was malformed, incompatible, or violates runtime invariants."""


class SaveEnvelope(StrictModel):
    """Portable runtime plus either authored IDs or fingerprinted generated truth."""

    schema_version: Literal[1, 2, 3, 4] = SAVE_SCHEMA_VERSION
    case_id: str
    location_id: str
    case_recipe: CaseRecipeSelection | None = None
    action_history: list[ActionHistoryEntry] | None = Field(
        default=None,
        max_length=MAX_ACTION_HISTORY,
    )
    story_presentation: StoryPresentationPatch | None = None
    generated_case: CaseDefinition | None = None
    generated_case_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    runtime: WorldRuntimeState

    @model_validator(mode="after")
    def require_replay_metadata(self) -> "SaveEnvelope":
        if (
            self.schema_version
            in {
                PRE_INTERVIEW_AGENT_SAVE_SCHEMA_VERSION,
                PRE_LOCATION_EVENT_SAVE_SCHEMA_VERSION,
                SAVE_SCHEMA_VERSION,
            }
            and self.action_history is None
        ):
            raise ValueError("replay-verified saves require action history")
        if (
            self.schema_version
            in {PRE_LOCATION_EVENT_SAVE_SCHEMA_VERSION, SAVE_SCHEMA_VERSION}
            and self.action_history is not None
        ):
            if any(
                entry.intent.get("kind") == "interview_exchange"
                and entry.interview_rules_version is None
                for entry in self.action_history
            ):
                raise ValueError(
                    "save schema v3+ requires rules metadata for every interview"
                )
        if self.action_history is not None:
            event_versions = [
                entry.location_event_rules_version
                for entry in self.action_history
            ]
            if self.schema_version == SAVE_SCHEMA_VERSION:
                if any(version is None for version in event_versions):
                    raise ValueError(
                        "save schema v4 requires location-event rules metadata"
                    )
                if event_versions != sorted(event_versions):
                    raise ValueError(
                        "legacy location-event rules may only form a history prefix"
                    )
            elif any(version is not None for version in event_versions):
                raise ValueError(
                    "pre-v4 saves cannot contain location-event rules metadata"
                )
        if (self.generated_case is None) != (self.generated_case_fingerprint is None):
            raise ValueError("generated case and fingerprint must appear together")
        if self.generated_case is not None:
            if self.case_recipe is not None:
                raise ValueError("generated saves cannot contain an authored recipe")
            if self.generated_case.id != self.case_id:
                raise ValueError("embedded generated case ID must match the save")
            if self.generated_case.location_package_id != self.location_id:
                raise ValueError("embedded generated case location must match the save")
        return self


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

    if runtime.schema_version != RUNTIME_SCHEMA_VERSION:
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
    private_memory_topics = {
        "private exchange",
        "private alibi",
        "private observation",
        "private authorized claim",
        "private reaction",
    }

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
            if memory.turn > runtime.turn:
                _fail("conversation memory occurs after the saved runtime")
            if character_id not in {memory.speaker_id, *memory.listener_ids}:
                _fail("conversation memory is stored by a non-participant")
            if memory.topic in private_memory_topics:
                listener_id = (
                    memory.listener_ids[0]
                    if len(memory.listener_ids) == 1
                    else None
                )
                speaker = runtime.characters.get(memory.speaker_id)
                listener = (
                    runtime.characters.get(listener_id)
                    if listener_id is not None
                    else None
                )
                if (
                    memory.speaker_id == victim_id
                    or listener_id
                    in {None, memory.speaker_id, victim_id, PLAYER_ID}
                    or speaker is None
                    or listener is None
                    or not speaker.alive
                    or not listener.alive
                    or not set(memory.referenced_fact_ids)
                    <= speaker.known_fact_ids
                    or (
                        memory.topic == "private observation"
                        and (
                            not memory.referenced_fact_ids
                            or not set(memory.referenced_fact_ids)
                            <= listener.known_fact_ids
                        )
                    )
                    or (
                        memory.topic != "private observation"
                        and memory.referenced_fact_ids
                    )
                    or not any(
                        counterpart == memory
                        for counterpart in listener.conversation_memory
                    )
                ):
                    _fail("private conversation memory is invalid")

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
    location_events = {event.id: event for event in location.events}
    survivor_ids = sorted(
        character_id
        for character_id, state in runtime.characters.items()
        if state.alive
    )
    for event in runtime.event_log:
        if event.id in event_ids or event.room_id not in room_ids:
            _fail("event log has a duplicate ID or invalid room")
        event_ids.add(event.id)
        _require_subset("event actors", event.actor_ids, cast_ids | {PLAYER_ID})
        _require_subset("event facts", event.fact_ids, fact_ids)
        _require_subset("event visibility", event.visible_to_character_ids, cast_ids | {PLAYER_ID})
        if event.turn > runtime.turn or event.minute > runtime.in_game_minute:
            _fail("event occurs after the saved runtime")
        definition = location_events.get(event.id)
        scheduled_turn = (
            location_event_turn(definition.trigger)
            if definition is not None
            else None
        )
        if (
            definition is None
            or definition.engine_effect != "atmosphere_only"
            or scheduled_turn is None
            or event.turn != scheduled_turn
            or event.minute
            != case.investigation_start_minute
            + scheduled_turn * case.turn_minutes
            or event.event_type != "atmosphere"
            or event.actor_ids
            or event.narration != definition.description
            or event.visible_to_character_ids != survivor_ids
            or not event.visible_to_player
            or event.fact_ids
        ):
            _fail("event log entry does not match its authored schedule")

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
    elif (
        runtime.phase == GamePhase.ENDED
        and runtime.result is None
        and runtime.turn < case.max_turns
    ):
        _fail("game ended before timeout without an accusation result")


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
    if envelope.schema_version not in {
        LEGACY_SAVE_SCHEMA_VERSION,
        PRE_INTERVIEW_AGENT_SAVE_SCHEMA_VERSION,
        PRE_LOCATION_EVENT_SAVE_SCHEMA_VERSION,
        SAVE_SCHEMA_VERSION,
    }:
        _fail("unsupported save schema version")
    if envelope.case_id != case.id or envelope.location_id != location.id:
        _fail("save references different authored content")
    if case.location_package_id != location.id:
        _fail("provided case and location are not compatible")
    if envelope.generated_case is not None:
        if envelope.generated_case != case:
            _fail("embedded generated case does not match restored truth")
        if envelope.generated_case_fingerprint != case_content_fingerprint(case):
            _fail("embedded generated case fingerprint does not match its truth")
        # A fingerprint detects accidental edits but is not an admission
        # decision: a local editor can recompute it.  Re-run the authoritative
        # structural/solvability validator before any embedded truth is used.
        if not validate_case(case, location).valid:
            _fail("embedded generated case is not a valid playable mystery")
    elif case.id.startswith("generated_"):
        _fail("generated save is missing embedded canonical truth")
    if envelope.case_recipe is not None:
        selection = envelope.case_recipe
        if selection.selected_case_id != envelope.case_id:
            _fail("saved recipe selection does not match the selected case")
        if selection.content_fingerprint != case_content_fingerprint(case):
            _fail("saved recipe content fingerprint does not match authored content")
        try:
            resolved = resolve_case_recipe(
                selection.recipe_id,
                selection.seed,
                selected_character_ids=(
                    selection.slot_card_ids.values()
                    if selection.cast_mode == "manual"
                    else None
                ),
            )
        except RecipeValidationError as error:
            raise SaveValidationError("saved recipe can no longer be resolved") from error
        if selection.slot_card_ids:
            if resolved != selection:
                _fail("saved recipe selection is not reproducible")
        elif not (
            selection.schema_version == 1
            and resolved.recipe_id == selection.recipe_id
            and resolved.seed == selection.seed
            and resolved.selected_case_id == selection.selected_case_id
        ):
            _fail("saved legacy recipe selection is not reproducible")
    if envelope.story_presentation is not None:
        try:
            validate_story_presentation(envelope.story_presentation, case, location)
        except ValueError as error:
            raise SaveValidationError("saved story presentation is not valid") from error
    validate_runtime_state(envelope.runtime, case, location)
    if envelope.schema_version in {
        PRE_INTERVIEW_AGENT_SAVE_SCHEMA_VERSION,
        PRE_LOCATION_EVENT_SAVE_SCHEMA_VERSION,
        SAVE_SCHEMA_VERSION,
    }:
        assert envelope.action_history is not None
        from game.engine import GameEngine

        replay = GameEngine(
            case,
            location,
            recipe_selection=envelope.case_recipe,
            story_presentation=envelope.story_presentation,
        )
        for entry in envelope.action_history:
            interview_rules_version = entry.interview_rules_version
            if (
                envelope.schema_version == PRE_INTERVIEW_AGENT_SAVE_SCHEMA_VERSION
                and entry.intent.get("kind") == "interview_exchange"
                and interview_rules_version is None
            ):
                interview_rules_version = (
                    2 if entry.interview_response_id is not None else 1
                )
            try:
                result = replay.apply(
                    entry.intent,
                    npc_action_ids=entry.npc_action_ids,
                    interview_response_id=entry.interview_response_id,
                    interview_rules_version=interview_rules_version,
                    location_event_rules_version=(
                        entry.location_event_rules_version
                        if envelope.schema_version == SAVE_SCHEMA_VERSION
                        else 0
                    ),
                )
            except (TypeError, ValueError, ValidationError) as error:
                raise SaveValidationError(
                    "save action history contains an invalid command"
                ) from error
            if not result.accepted:
                _fail("save action history contains a rejected command")
        if replay.runtime != envelope.runtime:
            _fail("save runtime does not match its action history")
    return envelope


def snapshot_engine(engine: Any) -> SaveEnvelope:
    """Create a validated envelope from a ``GameEngine``."""

    history = getattr(engine, "action_history", None)
    generated_case = (
        engine.case
        if engine.case.id.startswith("generated_")
        and engine.recipe_selection is None
        else None
    )
    envelope = SaveEnvelope(
        schema_version=(
            SAVE_SCHEMA_VERSION
            if history is not None
            else LEGACY_SAVE_SCHEMA_VERSION
        ),
        case_id=engine.case.id,
        location_id=engine.location.id,
        case_recipe=engine.recipe_selection,
        action_history=(
            [entry.model_copy(deep=True) for entry in history]
            if history is not None
            else None
        ),
        story_presentation=getattr(engine, "story_presentation", None),
        generated_case=generated_case,
        generated_case_fingerprint=(
            case_content_fingerprint(generated_case)
            if generated_case is not None
            else None
        ),
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

    engine = GameEngine(
        case,
        location,
        recipe_selection=envelope.case_recipe,
        story_presentation=envelope.story_presentation,
    )
    engine.runtime = envelope.runtime.model_copy(deep=True)
    if envelope.action_history is None:
        engine.action_history = None
    else:
        engine.action_history = []
        for entry in envelope.action_history:
            updates: dict[str, int] = {}
            if (
                envelope.schema_version
                == PRE_INTERVIEW_AGENT_SAVE_SCHEMA_VERSION
                and entry.intent.get("kind") == "interview_exchange"
                and entry.interview_rules_version is None
            ):
                updates["interview_rules_version"] = (
                    2 if entry.interview_response_id is not None else 1
                )
            if envelope.schema_version != SAVE_SCHEMA_VERSION:
                updates["location_event_rules_version"] = 0
            engine.action_history.append(
                entry.model_copy(deep=True, update=updates)
            )
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
    document = envelope.model_dump(mode="json")
    if envelope.generated_case is None:
        document.pop("generated_case", None)
        document.pop("generated_case_fingerprint", None)
    if envelope.schema_version == LEGACY_SAVE_SCHEMA_VERSION:
        document.pop("action_history", None)
    payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
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
    """Load authored IDs or embedded generated truth and restore engine state."""

    envelope = read_save(save_root, filename)
    if case_loader is None or location_loader is None:
        from game.content import load_case, load_location

        case_loader = case_loader or load_case
        location_loader = location_loader or load_location
    try:
        if envelope.generated_case is not None:
            case = envelope.generated_case
            if (
                envelope.generated_case_fingerprint
                != case_content_fingerprint(case)
            ):
                raise SaveValidationError(
                    "embedded generated case fingerprint does not match its truth"
                )
        elif envelope.case_recipe is not None and envelope.case_recipe.slot_card_ids:
            case = materialize_case_recipe(envelope.case_recipe)
        else:
            case = case_loader(envelope.case_id)
        location = location_loader(envelope.location_id)
    except SaveValidationError:
        raise
    except (OSError, ValueError, FileNotFoundError) as error:
        raise SaveValidationError("save references unavailable authored content") from error
    return restore_engine(envelope, case, location)
