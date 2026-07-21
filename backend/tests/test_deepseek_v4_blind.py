"""Black-box route and transcript tests for the restricted blind surface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from experiments.deepseek_v4_blind import BlindTranscriptRecorder, build_blind_app
from game.service import GameService


def _client(tmp_path: Path):
    service = GameService(tmp_path / "saves")
    service.start()
    recorder = BlindTranscriptRecorder(tmp_path / "transcript.jsonl", session_id="opaque-session")
    return TestClient(build_blind_app(service=service, recorder=recorder)), recorder


def test_blind_app_exposes_only_player_routes_and_no_hidden_response_fields(
    tmp_path: Path,
) -> None:
    client, recorder = _client(tmp_path)

    assert client.get("/api/health").json() == {"status": "ready"}
    bootstrap = client.get("/api/game/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["game"]["phase"] == "discovery"
    assert "provider" not in bootstrap.json()["catalog"]["generation"]
    assert client.get("/api/game/state").status_code == 200
    assert client.get("/api/game/saves/v2").json()["saves"] == []

    forbidden = (
        ("GET", "/api/game/debrief"),
        ("POST", "/api/game/new"),
        ("POST", "/api/game/demo"),
        ("POST", "/api/game/saves/v2"),
        ("GET", "/api/settings"),
        ("GET", "/api/models"),
        ("GET", "/api/characters"),
        ("GET", "/openapi.json"),
    )
    for method, path in forbidden:
        response = client.request(method, path)
        assert response.status_code in {404, 405}

    records = [
        json.loads(line)
        for line in recorder.path.read_text(encoding="utf-8").splitlines()
    ]
    serialized_responses = json.dumps([record["response"] for record in records]).casefold()
    for forbidden_key in (
        "canonical_truth",
        "case_document",
        "culprit_id",
        "murderer_id",
        "private_overlay",
        "pair_id",
        "run_id",
        '"model"',
        '"provider"',
    ):
        assert forbidden_key not in serialized_responses


def test_blind_transcript_records_rejections_and_seals_against_tampering(
    tmp_path: Path,
) -> None:
    client, recorder = _client(tmp_path)

    rejected = client.post("/api/game/action", json={"kind": "move", "room_id": None})
    assert rejected.status_code == 422
    accepted = client.post("/api/game/action", json={"kind": "advance_opening"})
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is True

    seal = recorder.seal(reason="coordinator_freeze")
    assert seal["record_count"] == 2
    assert recorder.verify_seal() is True
    assert client.post("/api/game/action", json={"kind": "review_notebook"}).status_code == 409
    assert client.get("/api/game/state").status_code == 409

    with recorder.path.open("a", encoding="utf-8") as handle:
        handle.write("{}\n")
    assert recorder.verify_seal() is False


def test_runtime_provider_stop_seals_after_returning_committed_public_result(
    tmp_path: Path,
) -> None:
    service = GameService(tmp_path / "saves")
    service.start()
    asyncio.run(service.action({"kind": "advance_opening"}))
    recorder = BlindTranscriptRecorder(tmp_path / "provider-stop.jsonl")
    client = TestClient(
        build_blind_app(
            service=service,
            recorder=recorder,
            provider_stop=lambda: "provider_unavailable",
        )
    )

    destination = service.state().player_room.exits[0]
    response = client.post(
        "/api/game/action",
        json={"kind": "move", "room_id": destination},
    )
    assert response.status_code == 200
    assert response.json()["committed"] is True
    assert recorder.sealed is True
    seal = json.loads(recorder.seal_path.read_text(encoding="utf-8"))
    assert seal["reason"] == "runtime_provider_stop"


def test_adversarial_surface_exposes_validated_save_load_without_debrief(
    tmp_path: Path,
) -> None:
    service = GameService(tmp_path / "saves")
    service.start()
    asyncio.run(service.action({"kind": "advance_opening"}))
    recorder = BlindTranscriptRecorder(tmp_path / "adversarial.jsonl")
    client = TestClient(
        build_blind_app(
            service=service,
            recorder=recorder,
            allow_save_load=True,
        )
    )

    saved = client.post("/api/game/saves/v2", json={"filename": "checkpoint"})
    assert saved.status_code == 200
    assert saved.json()["filename"] == "checkpoint.json"
    original_room = service.state().player_room.id
    destination = service.state().player_room.exits[0]
    moved = client.post(
        "/api/game/action",
        json={"kind": "move", "room_id": destination},
    )
    assert moved.json()["committed"] is True
    loaded = client.post("/api/game/saves/v2/checkpoint.json/load")
    assert loaded.status_code == 200
    assert loaded.json()["game"]["player_room"]["id"] == original_room
    assert client.get("/api/game/saves/v2").json()["saves"] == ["checkpoint.json"]

    escaped = client.post("/api/game/saves/v2", json={"filename": "../outside"})
    assert escaped.status_code == 400
    assert client.get("/api/game/debrief").status_code == 404
