"""HTTP contracts for the local CCv3 draft editor boundary."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import main
import routers.cards as cards_router
from game.card_library import MAX_CARD_BYTES
from game.content import load_character_card


def test_validate_preview_never_returns_prompt_or_card(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cards_router, "CARD_DRAFT_ROOT", tmp_path)
    document = load_character_card("zara_okonkwo").model_dump(mode="json")
    document["data"]["system_prompt"] = "PRIVATE EDITOR PROMPT"

    with TestClient(main.app) as client:
        response = client.post(
            "/api/cards/validate",
            json={"raw_json": json.dumps(document), "character_id": "zara_draft"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["preview"]["character_id"] == "zara_draft"
    assert "card" not in payload
    assert "PRIVATE EDITOR PROMPT" not in response.text


def test_save_list_collision_replace_and_export_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cards_router, "CARD_DRAFT_ROOT", tmp_path)
    raw = load_character_card("captain_marcus_drake").model_dump_json()
    body = {"raw_json": raw, "character_id": "captain_draft"}

    with TestClient(main.app) as client:
        saved = client.post("/api/cards/drafts", json=body)
        assert saved.status_code == 200
        assert saved.json()["filename"] == "captain_draft.json"
        assert client.post("/api/cards/drafts", json=body).status_code == 409
        assert client.post(
            "/api/cards/drafts", json={**body, "replace": True}
        ).status_code == 200

        listed = client.get("/api/cards/drafts").json()["drafts"]
        assert [item["character_id"] for item in listed] == ["captain_draft"]
        exported = client.get("/api/cards/drafts/captain_draft/export")

    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/json"
    assert exported.headers["content-disposition"].endswith('"captain_draft.json"')
    assert json.loads(exported.content)["spec"] == "chara_card_v3"


def test_invalid_huge_and_traversal_requests_do_not_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cards_router, "CARD_DRAFT_ROOT", tmp_path)
    raw = load_character_card("zara_okonkwo").model_dump_json()

    with TestClient(main.app) as client:
        malformed = client.post("/api/cards/drafts", json={"raw_json": "{"})
        traversal = client.post(
            "/api/cards/drafts",
            json={"raw_json": raw, "character_id": "../escape"},
        )
        huge = client.post(
            "/api/cards/validate",
            json={"raw_json": "x" * (MAX_CARD_BYTES + 1)},
        )

    assert malformed.status_code == 422
    assert traversal.status_code == 422
    assert huge.status_code == 422
    assert not list(tmp_path.iterdir())
