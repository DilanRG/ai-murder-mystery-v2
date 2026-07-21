"""Red contracts for deterministic scheduled location events."""

from __future__ import annotations

import json

import pytest

from game.actions import AdvanceOpeningIntent, SearchIntent
from game.content import load_case, load_location
from game.engine import GameEngine
from game.models import LocationPackage
from game.persistence import SaveValidationError, load_engine, restore_engine, snapshot_engine, write_save
from game.validator import validate_case, validate_location_package


def _engine() -> GameEngine:
    engine = GameEngine(load_case("ashwick_sample"), load_location("ashwick_manor"))
    assert engine.apply(AdvanceOpeningIntent()).accepted
    return engine


def _advance(engine: GameEngine, turns: int) -> list[object]:
    return [
        engine.apply(SearchIntent(object_id="hall_clock"))
        for _ in range(turns)
    ]


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("trigger", "turn_06", "invalid_event_trigger"),
        ("trigger", "at_turn_6", "invalid_event_trigger"),
        ("trigger", "turn_0", "invalid_event_trigger"),
        ("engine_effect", "unlock_every_door", "unsupported_event_effect"),
    ),
)
def test_location_events_require_a_strict_turn_trigger_and_supported_effect(
    field: str,
    value: str,
    code: str,
) -> None:
    payload = load_location("ashwick_manor").model_dump(mode="json")
    payload["events"][0][field] = value

    report = validate_location_package(LocationPackage.model_validate(payload))

    assert code in {issue.code for issue in report.issues}


def test_location_event_cannot_be_scheduled_after_the_case_ends() -> None:
    payload = load_location("ashwick_manor").model_dump(mode="json")
    payload["events"][0]["trigger"] = "turn_9999"

    report = validate_case(
        load_case("ashwick_sample"),
        LocationPackage.model_validate(payload),
    )

    assert "unreachable_event_trigger" in {
        issue.code for issue in report.issues
    }


def test_ashwick_turn_six_event_is_recorded_once_and_visible_to_every_survivor() -> None:
    engine = _engine()
    results = _advance(engine, 7)
    event_definition = next(
        event for event in engine.location.events if event.id == "storm_intensifies"
    )

    assert event_definition.description not in results[4].events
    assert event_definition.description in results[5].events
    assert event_definition.description not in results[6].events
    assert [event.id for event in engine.runtime.event_log].count(event_definition.id) == 1

    event = next(event for event in engine.runtime.event_log if event.id == event_definition.id)
    assert event.turn == 6
    assert event.minute == engine.case.investigation_start_minute + 6 * engine.case.turn_minutes
    assert event.event_type == "atmosphere"
    assert event.room_id == engine.runtime.player_room_id
    assert event.actor_ids == []
    assert event.visible_to_player is True
    assert set(event.visible_to_character_ids) == {
        character_id
        for character_id, state in engine.runtime.characters.items()
        if state.alive
    }
    assert event.fact_ids == []
    assert len(event.narration) <= 500


def test_due_event_is_in_the_frozen_npc_preview_without_mutating_live_state() -> None:
    engine = _engine()
    _advance(engine, 5)
    due = next(
        event for event in engine.location.events if event.id == "storm_intensifies"
    )

    preview = engine.preview(SearchIntent(object_id="hall_clock"))

    assert due.description in preview.result.events
    assert preview.npc_request is not None
    assert due.description in preview.npc_request.snapshot.public_event_summaries
    assert engine.runtime.turn == 5
    assert engine.runtime.event_log == []


def test_ashwick_turn_eighteen_event_is_once_only_and_replay_save_is_deterministic(
    tmp_path,
) -> None:
    engine = _engine()
    results = _advance(engine, 19)

    causeway_update = next(
        event for event in engine.location.events if event.id == "causeway_update"
    )
    assert causeway_update.description in results[17].events
    assert causeway_update.description not in results[18].events
    assert [
        event.id
        for event in engine.runtime.event_log
        if event.id in {"storm_intensifies", "causeway_update"}
    ] == [
        "storm_intensifies",
        "causeway_update",
    ]

    saved = write_save(engine, tmp_path, "scheduled-events.json")
    restored = load_engine(tmp_path, saved.name)

    assert restored.runtime == engine.runtime
    assert [event.model_dump(mode="json") for event in restored.runtime.event_log] == [
        event.model_dump(mode="json") for event in engine.runtime.event_log
    ]


def test_v3_save_before_turn_six_migrates_and_still_emits_the_due_event() -> None:
    engine = _engine()
    _advance(engine, 5)
    old_v3 = snapshot_engine(engine).model_dump(mode="json")
    assert old_v3["schema_version"] == 4
    old_v3["schema_version"] = 3
    for entry in old_v3["action_history"]:
        entry.pop("location_event_rules_version")

    restored = restore_engine(old_v3, engine.case, engine.location)
    sixth = restored.apply(SearchIntent(object_id="hall_clock"))

    assert (
        next(
            event for event in restored.location.events if event.id == "storm_intensifies"
        ).description
        in sixth.events
    )
    assert snapshot_engine(restored).schema_version == 4


@pytest.mark.parametrize("turns", (6, 18))
def test_v3_save_after_scheduled_turn_preserves_history_without_retroactive_event(
    turns: int,
) -> None:
    engine = _engine()
    _advance(engine, turns)
    old_v3 = snapshot_engine(engine).model_dump(mode="json")
    old_v3["schema_version"] = 3
    old_v3["runtime"]["event_log"] = []
    for entry in old_v3["action_history"]:
        entry.pop("location_event_rules_version")

    restored = restore_engine(old_v3, engine.case, engine.location)

    assert restored.runtime.event_log == []
    assert all(
        entry.location_event_rules_version == 0
        for entry in restored.action_history
    )
    next_turn = restored.apply(SearchIntent(object_id="hall_clock"))
    assert next_turn.accepted
    assert restored.runtime.event_log == []
    assert snapshot_engine(restored).schema_version == 4


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("narration", "A forged event account."),
        ("event_type", "unlock_every_door"),
        ("visible_to_player", False),
        ("fact_ids", ["fact_murderer_identity"]),
    ),
)
def test_v4_rejects_tampered_scheduled_event_records(
    field: str,
    value: object,
) -> None:
    engine = _engine()
    _advance(engine, 6)
    payload = snapshot_engine(engine).model_dump(mode="json")
    payload["runtime"]["event_log"][0][field] = value

    with pytest.raises(SaveValidationError, match="authored schedule"):
        restore_engine(payload, engine.case, engine.location)


def test_v4_requires_explicit_monotonic_location_event_history_rules() -> None:
    engine = _engine()
    _advance(engine, 2)
    missing = snapshot_engine(engine).model_dump(mode="json")
    missing["action_history"][0].pop("location_event_rules_version")
    with pytest.raises(SaveValidationError, match="supported schema"):
        restore_engine(missing, engine.case, engine.location)

    reversed_prefix = snapshot_engine(engine).model_dump(mode="json")
    reversed_prefix["action_history"][0]["location_event_rules_version"] = 1
    reversed_prefix["action_history"][1]["location_event_rules_version"] = 0
    with pytest.raises(SaveValidationError, match="supported schema"):
        restore_engine(reversed_prefix, engine.case, engine.location)


def test_v3_migration_keeps_rejecting_tampered_non_event_runtime() -> None:
    engine = _engine()
    _advance(engine, 5)
    old_v3 = json.loads(json.dumps(snapshot_engine(engine).model_dump(mode="json")))
    old_v3["schema_version"] = 3
    for entry in old_v3["action_history"]:
        entry.pop("location_event_rules_version")
    old_v3["runtime"]["player_room_id"] = "forged_room"

    with pytest.raises(SaveValidationError, match="player room"):
        restore_engine(old_v3, engine.case, engine.location)
