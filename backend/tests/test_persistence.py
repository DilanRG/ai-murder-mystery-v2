"""Save/load tests for validated deterministic runtime snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from game.actions import AccuseIntent, AdvanceOpeningIntent, MoveIntent, SearchIntent
from game.content import load_case, load_location
from game.engine import GameEngine
from game.persistence import (
    SaveValidationError,
    load_engine,
    read_save,
    restore_engine,
    safe_save_path,
    snapshot_engine,
    write_save,
)
from game.recipes import resolve_case_recipe, resolve_materialized_case_recipe


def make_engine() -> GameEngine:
    return GameEngine(load_case("ashwick_sample"), load_location("ashwick_manor"))


def test_save_round_trip_restores_runtime_without_embedded_truth(tmp_path: Path) -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))
    engine.apply(SearchIntent(object_id="library_desk"))

    written = write_save(engine, tmp_path, "ashwick-slot.json")
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema_version",
        "case_id",
        "location_id",
        "case_recipe",
        "action_history",
        "story_presentation",
        "runtime",
    }
    assert payload["schema_version"] == 2
    assert payload["case_recipe"] is None
    # Runtime may legitimately contain opaque fact IDs, but never a copied
    # authored solution object or an authored murder-truth field.
    assert "murder" not in payload["runtime"]
    assert "solution" not in payload["runtime"]

    restored = load_engine(tmp_path, "ashwick-slot.json")
    assert restored.runtime == engine.runtime
    assert restored.case is not engine.case
    assert restored.case.id == "ashwick_sample"


def test_snapshot_and_restore_accept_a_valid_in_memory_round_trip() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    envelope = snapshot_engine(engine)
    restored = restore_engine(envelope.model_dump(mode="json"), engine.case, engine.location)
    assert restored.runtime == engine.runtime
    assert restored.action_history == engine.action_history


def test_v2_action_history_rejects_forged_evidence_progression() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    payload = snapshot_engine(engine).model_dump(mode="json")
    evidence_id = "ev_library_poker"
    evidence = payload["runtime"]["evidence"][evidence_id]
    evidence.update(
        {
            "condition": "collected",
            "current_slot_id": None,
            "discovered_by_character_ids": ["player"],
            "discovered_by_player": True,
            "discovered_turn": 0,
        }
    )
    payload["runtime"]["player_knowledge"]["discovered_evidence_ids"] = [
        evidence_id
    ]
    payload["runtime"]["player_knowledge"]["known_fact_ids"] = list(
        engine.case.evidence[evidence_id].fact_ids
    )

    with pytest.raises(SaveValidationError, match="action history"):
        restore_engine(payload, engine.case, engine.location)


def test_v2_rejects_removed_or_invalid_history_but_v1_legacy_still_loads() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))
    payload = snapshot_engine(engine).model_dump(mode="json")

    removed = json.loads(json.dumps(payload))
    removed["action_history"] = removed["action_history"][:-1]
    with pytest.raises(SaveValidationError, match="action history"):
        restore_engine(removed, engine.case, engine.location)

    invalid = json.loads(json.dumps(payload))
    invalid["action_history"][0]["intent"] = {"kind": "not_real"}
    with pytest.raises(SaveValidationError, match="action history"):
        restore_engine(invalid, engine.case, engine.location)

    legacy = json.loads(json.dumps(payload))
    legacy["schema_version"] = 1
    legacy.pop("action_history")
    restored = restore_engine(legacy, engine.case, engine.location)
    assert restored.runtime == engine.runtime
    assert restored.action_history is None


def test_v2_rejects_unbounded_or_oversized_npc_history_selections() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    payload = snapshot_engine(engine).model_dump(mode="json")

    too_many = json.loads(json.dumps(payload))
    too_many["action_history"][0]["npc_action_ids"] = {
        f"character_{index}": "stay" for index in range(9)
    }
    with pytest.raises(SaveValidationError, match="supported schema"):
        restore_engine(too_many, engine.case, engine.location)

    oversized = json.loads(json.dumps(payload))
    oversized["action_history"][0]["npc_action_ids"] = {"x" * 101: "stay"}
    with pytest.raises(SaveValidationError, match="supported schema"):
        restore_engine(oversized, engine.case, engine.location)


def test_impossible_early_ended_save_is_rejected() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    payload = snapshot_engine(engine).model_dump(mode="json")
    payload["runtime"]["phase"] = "ended"
    payload["runtime"]["result"] = None

    with pytest.raises(SaveValidationError, match="ended before timeout"):
        restore_engine(payload, engine.case, engine.location)


def test_seeded_recipe_round_trip_is_reproducible_and_old_v1_save_still_loads() -> None:
    selection, case = resolve_materialized_case_recipe("ashwick_manor_dual_spines", 42)
    location = load_location("ashwick_manor")
    engine = GameEngine.create(case, location, recipe_selection=selection)

    envelope = snapshot_engine(engine)
    restored = restore_engine(envelope, case, location)
    assert restored.recipe_selection == selection
    assert restored.runtime == engine.runtime

    legacy_payload = envelope.model_dump(mode="json")
    legacy_payload.pop("case_recipe")
    legacy = restore_engine(legacy_payload, case, location)
    assert legacy.recipe_selection is None


def test_tampered_recipe_selection_is_rejected() -> None:
    selection, case = resolve_materialized_case_recipe("ashwick_manor_dual_spines", 0)
    location = load_location("ashwick_manor")
    engine = GameEngine.create(case, location, recipe_selection=selection)

    forged = snapshot_engine(engine).model_dump(mode="json")
    forged["case_recipe"]["content_fingerprint"] = "0" * 64
    with pytest.raises(SaveValidationError, match="fingerprint"):
        restore_engine(forged, case, location)

    opposite_seed = next(
        seed
        for seed in range(1, 100)
        if resolve_case_recipe("ashwick_manor_dual_spines", seed).selected_case_id
        != selection.selected_case_id
    )
    forged = snapshot_engine(engine).model_dump(mode="json")
    forged["case_recipe"]["seed"] = opposite_seed
    with pytest.raises(SaveValidationError, match="reproducible"):
        restore_engine(forged, case, location)


@pytest.mark.parametrize("filename", ["../outside.json", "nested/slot.json", "slot.txt", "", "."])
def test_save_filename_cannot_escape_configured_root(tmp_path: Path, filename: str) -> None:
    with pytest.raises(SaveValidationError):
        safe_save_path(tmp_path, filename)


def test_tampered_entity_set_and_room_are_rejected(tmp_path: Path) -> None:
    engine = make_engine()
    saved = write_save(engine, tmp_path, "tampered.json")
    payload = json.loads(saved.read_text(encoding="utf-8"))
    del payload["runtime"]["characters"]["edgar_blackwood"]
    saved.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SaveValidationError, match="characters keys"):
        load_engine(tmp_path, "tampered.json")

    payload = snapshot_engine(engine).model_dump(mode="json")
    payload["runtime"]["player_room_id"] = "not_a_room"
    with pytest.raises(SaveValidationError, match="player room"):
        restore_engine(payload, engine.case, engine.location)


def test_tampered_interview_and_result_phase_are_rejected() -> None:
    engine = make_engine()
    payload = snapshot_engine(engine).model_dump(mode="json")
    payload["runtime"]["active_interview"] = {
        "character_id": "edgar_blackwood",
        "started_turn": 0,
        "exchanges_used": 0,
        "max_exchanges": 3,
        "statement_ids": [],
    }
    with pytest.raises(SaveValidationError, match="interview"):
        restore_engine(payload, engine.case, engine.location)

    payload = snapshot_engine(engine).model_dump(mode="json")
    payload["runtime"]["result"] = {
        "accused_character_id": "edgar_blackwood",
        "correct_culprit": True,
        "support_score": 3,
        "submitted_method": "",
        "submitted_motive": "",
        "submitted_timeline": "",
        "method_supported": False,
        "motive_supported": False,
        "timeline_supported": False,
        "solved": True,
        "selected_evidence_ids": [],
        "selected_timeline_fact_ids": [],
        "summary": "forged",
    }
    with pytest.raises(SaveValidationError, match="result requires"):
        restore_engine(payload, engine.case, engine.location)


def test_blank_claim_accusation_round_trips_but_cannot_claim_support() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    accusation = engine.apply(AccuseIntent(character_id="edgar_blackwood"))
    assert accusation.accepted and engine.runtime.result is not None
    assert engine.runtime.result.support_score == 0
    assert not engine.runtime.result.method_supported

    restored = restore_engine(snapshot_engine(engine), engine.case, engine.location)
    assert restored.runtime == engine.runtime

    forged = snapshot_engine(engine).model_dump(mode="json")
    forged["runtime"]["result"]["method_supported"] = True
    with pytest.raises(SaveValidationError, match="support flags"):
        restore_engine(forged, engine.case, engine.location)


def test_read_save_is_schema_only_until_restore_validates_authored_references(tmp_path: Path) -> None:
    engine = make_engine()
    path = write_save(engine, tmp_path, "schema-only.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["runtime"]["case_id"] = "forged_case"
    path.write_text(json.dumps(payload), encoding="utf-8")
    # Shape parsing succeeds, but restoration checks it against authored truth.
    assert read_save(tmp_path, "schema-only.json").runtime.case_id == "forged_case"
    with pytest.raises(SaveValidationError, match="runtime does not belong"):
        load_engine(tmp_path, "schema-only.json")
