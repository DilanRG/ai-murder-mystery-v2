"""Contract tests for the deterministic HTTP surface.

These tests use the real Ashwick authored content.  They deliberately inspect
responses rather than canonical models so accidental truth serialization is
caught at the transport boundary.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import main


def _client(tmp_path):
    main._session.engine = None
    main._session.llm = None  # A no-key game is a core MVP requirement.
    main._session.save_root = tmp_path
    return TestClient(main.app)


def test_no_key_start_catalog_opening_and_safe_state(tmp_path):
    with _client(tmp_path) as client:
        catalog = client.get("/api/game/catalog")
        assert catalog.status_code == 200
        payload = catalog.json()
        assert payload["default_case_id"] == "ashwick_sample"
        assert len(payload["locations"][0]["rooms"]) >= 8
        assert len(payload["characters"]) == 8
        assert "role" not in json.dumps(payload).lower()

        response = client.post("/api/game/new", json={})
        assert response.status_code == 200
        opening = response.json()["game"]
        assert opening["phase"] == "discovery"
        assert opening["opening"]["victim_name"]

        state = client.get("/api/game/state")
        assert state.status_code == 200
        serialized = json.dumps(state.json()).lower()
        assert '"murderer"' not in serialized
        assert "private_motive" not in serialized
        assert "cover_story" not in serialized


def test_action_validation_and_opening_progression(tmp_path):
    with _client(tmp_path) as client:
        client.post("/api/game/new", json={})
        assert client.post("/api/game/action", json={"kind": "not_real"}).status_code == 422
        assert client.post("/api/game/action", json=["advance_opening"]).status_code == 422

        result = client.post("/api/game/action", json={"kind": "advance_opening"})
        assert result.status_code == 200
        body = result.json()
        assert body["accepted"] is True
        assert body["committed"] is False
        assert body["game"]["phase"] == "investigation"

        invalid = client.post("/api/game/action", json={"kind": "move", "room_id": "not-a-room"})
        assert invalid.status_code == 200
        assert invalid.json()["accepted"] is False


def test_save_load_and_debrief_gating(tmp_path):
    with _client(tmp_path) as client:
        client.post("/api/game/new", json={})
        assert client.get("/api/game/debrief").status_code == 400

        saved = client.post("/api/game/saves/v1", json={"filename": "ashwick.json"})
        assert saved.status_code == 200
        assert saved.json()["filename"] == "ashwick.json"
        assert client.get("/api/game/saves/v1").json()["saves"] == ["ashwick.json"]

        client.post("/api/game/action", json={"kind": "advance_opening"})
        loaded = client.post("/api/game/saves/v1/ashwick.json/load")
        assert loaded.status_code == 200
        assert loaded.json()["game"]["phase"] == "discovery"

        client.post("/api/game/action", json={"kind": "advance_opening"})
        accuse = client.post(
            "/api/game/action",
            json={"kind": "accuse", "character_id": "edgar_blackwood"},
        )
        assert accuse.status_code == 200
        assert accuse.json()["game"]["phase"] == "ended"

        debrief = client.get("/api/game/debrief")
        assert debrief.status_code == 200
        solution = debrief.json()["solution"]
        assert solution["culprit_id"] == "edgar_blackwood"
        assert solution["method"]
