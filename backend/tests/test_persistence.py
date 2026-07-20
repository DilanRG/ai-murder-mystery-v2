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


def make_engine() -> GameEngine:
    return GameEngine(load_case("ashwick_sample"), load_location("ashwick_manor"))


def test_save_round_trip_restores_runtime_without_embedded_truth(tmp_path: Path) -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))
    engine.apply(SearchIntent(object_id="library_desk"))

    written = write_save(engine, tmp_path, "ashwick-slot.json")
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert set(payload) == {"schema_version", "case_id", "location_id", "runtime"}
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
