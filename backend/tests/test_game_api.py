"""Contract tests for the deterministic HTTP surface.

These tests use the real Ashwick authored content.  They deliberately inspect
responses rather than canonical models so accidental truth serialization is
caught at the transport boundary.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main


def _client(tmp_path):
    main._session.engine = None
    main._session.llm = None  # A no-key game is a core MVP requirement.
    main._session.save_root = tmp_path
    return TestClient(main.app)


def _public_cast_ids(payload: dict[str, object]) -> set[str]:
    game = payload["game"]
    assert isinstance(game, dict)
    cast_ids = {str(suspect["id"]) for suspect in game["suspects"]}
    opening = game.get("opening")
    if isinstance(opening, dict):
        cast_ids.add(str(opening["victim_id"]))
    return cast_ids


def test_no_key_demo_catalog_opening_and_safe_state(tmp_path):
    with _client(tmp_path) as client:
        social_preview = client.get("/og.png")
        assert social_preview.status_code == 200
        assert social_preview.headers["content-type"] == "image/png"

        catalog = client.get("/api/game/catalog")
        assert catalog.status_code == 200
        payload = catalog.json()
        assert payload["default_case_id"] == "ashwick_sample"
        assert payload["default_recipe_id"] == "ashwick_manor_dual_spines"
        assert payload["recipes"][0]["variation_count"] == 13_122
        assert payload["recipes"][0]["cast_variation_count"] == 6_561
        assert payload["recipes"][0]["character_pool_size"] == 24
        serialized_recipes = json.dumps(payload["recipes"]).lower()
        assert "culprit" not in serialized_recipes
        assert "fingerprint" not in serialized_recipes
        assert "case_ids" not in serialized_recipes
        assert len(payload["locations"][0]["rooms"]) >= 8
        assert len(payload["characters"]) == 24
        assert "role" not in json.dumps(payload).lower()
        for character in payload["characters"]:
            assert character["portrait_url"] == (
                f"/assets/characters/{character['id']}/portrait-placeholder.svg"
            )
            assert "assets" not in character
            portrait = client.get(character["portrait_url"])
            assert portrait.status_code == 200
            assert "svg" in portrait.headers["content-type"]

        response = client.post("/api/game/demo", json={})
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
        for character in state.json()["present_characters"]:
            assert character["portrait_url"].startswith("/assets/characters/")


def test_seeded_recipe_start_is_reproducible_and_does_not_leak_selection_metadata(tmp_path):
    with _client(tmp_path) as client:
        titles_by_seed = {}
        for seed in range(32):
            response = client.post(
                "/api/game/demo",
                json={"recipe_id": "ashwick_manor_dual_spines", "seed": seed},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["recipe"] == {
                "recipe_id": "ashwick_manor_dual_spines",
                "schema_version": 2,
                "seed": seed,
                "cast_mode": "automatic",
                "story_source": "fallback",
                "story_status": "ready",
            }
            assert "selected_case_id" not in json.dumps(payload["recipe"])
            titles_by_seed[seed] = payload["game"]["case_title"]

        assert len(set(titles_by_seed.values())) == 2
        repeated_seed = next(iter(titles_by_seed))
        repeated = client.post(
            "/api/game/demo",
            json={"recipe_id": "ashwick_manor_dual_spines", "seed": repeated_seed},
        ).json()
        assert repeated["game"]["case_title"] == titles_by_seed[repeated_seed]


def test_recipe_seed_boundary_and_conflicting_inputs_are_rejected(tmp_path):
    with _client(tmp_path) as client:
        for seed in (0, 1_000_000, 2_147_483_648, (1 << 53) - 1):
            response = client.post(
                "/api/game/demo",
                json={"recipe_id": "ashwick_manor_dual_spines", "seed": seed},
            )
            assert response.status_code == 200

        invalid_payloads = (
            {"recipe_id": "ashwick_manor_dual_spines"},
            {"seed": 0},
            {"recipe_id": "ashwick_manor_dual_spines", "seed": -1},
            {"recipe_id": "ashwick_manor_dual_spines", "seed": 1 << 53},
            {"recipe_id": "ashwick_manor_dual_spines", "seed": True},
            {"recipe_id": "ashwick_manor_dual_spines", "seed": "42"},
            {
                "recipe_id": "ashwick_manor_dual_spines",
                "seed": 42,
                "case_id": "ashwick_sample",
            },
            {"unexpected": "field"},
        )
        for payload in invalid_payloads:
            assert client.post("/api/game/demo", json=payload).status_code == 422


def test_recipe_selection_survives_save_load_without_public_spine_id(tmp_path):
    with _client(tmp_path) as client:
        started = client.post(
            "/api/game/demo",
            json={"recipe_id": "ashwick_manor_dual_spines", "seed": 42},
        ).json()
        title = started["game"]["case_title"]
        selected_cast = _public_cast_ids(started)
        assert len(selected_cast) == 8
        assert client.post("/api/game/saves/v1", json={"filename": "seeded"}).status_code == 200

        replacement = client.post(
            "/api/game/demo",
            json={"recipe_id": "ashwick_manor_dual_spines", "seed": 43},
        ).json()
        assert _public_cast_ids(replacement) != selected_cast
        loaded = client.post("/api/game/saves/v1/seeded.json/load")
        assert loaded.status_code == 200
        assert loaded.json()["game"]["case_title"] == title
        assert _public_cast_ids(loaded.json()) == selected_cast
        assert loaded.json()["recipe"] == {
            "recipe_id": "ashwick_manor_dual_spines",
            "schema_version": 2,
            "seed": 42,
            "cast_mode": "automatic",
            "story_source": "fallback",
            "story_status": "ready",
        }


def test_action_validation_and_opening_progression(tmp_path):
    with _client(tmp_path) as client:
        client.post("/api/game/demo", json={})
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
        client.post("/api/game/demo", json={})
        assert client.get("/api/game/debrief").status_code == 400

        saved = client.post("/api/game/saves/v2", json={"filename": "ashwick.json"})
        assert saved.status_code == 200
        assert saved.json()["schema_version"] == 3
        assert saved.json()["filename"] == "ashwick.json"
        friendly = client.post("/api/game/saves/v2", json={"filename": "second-slot"})
        assert friendly.status_code == 200
        assert friendly.json()["filename"] == "second-slot.json"
        assert client.get("/api/game/saves/v2").json()["saves"] == ["ashwick.json", "second-slot.json"]
        assert client.get("/api/game/saves/v1").json()["schema_version"] == 3

        client.post("/api/game/action", json={"kind": "advance_opening"})
        loaded = client.post("/api/game/saves/v2/ashwick.json/load")
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


def test_interview_portrayal_is_optional_and_never_replaces_canonical_statement(tmp_path):
    class ValidLLM:
        async def generate(self, messages, **kwargs):
            self.messages = messages
            self.kwargs = kwargs
            return SimpleNamespace(
                content='{"utterance":"I remained in the great hall, detective.","referenced_fact_ids":[]}'
            )

    with _client(tmp_path) as client:
        llm = ValidLLM()
        main._session.llm = llm
        client.post("/api/game/demo", json={})
        client.post("/api/game/action", json={"kind": "advance_opening"})
        client.post(
            "/api/game/action",
            json={"kind": "begin_interview", "character_id": "inspector_elena_hayes"},
        )
        response = client.post(
            "/api/game/action",
            json={"kind": "interview_exchange", "message": "Where were you?"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["portrayal"]["source"] == "provider"
        assert payload["portrayal"]["surface_utterance"] == "I remained in the great hall, detective."
        assert payload["dialogue"]["text"] == payload["portrayal"]["canonical_claim"]
        assert payload["dialogue"]["text"] != payload["portrayal"]["surface_utterance"]
        sent_text = "\n".join(message.content for message in llm.messages)
        assert "private_motive" not in sent_text
        assert "murderer_id" not in sent_text


def test_failed_portrayal_provider_falls_back_after_engine_commits_statement(tmp_path):
    class FailingLLM:
        async def generate(self, messages, **kwargs):
            raise RuntimeError("offline")

    with _client(tmp_path) as client:
        main._session.llm = FailingLLM()
        client.post("/api/game/demo", json={})
        client.post("/api/game/action", json={"kind": "advance_opening"})
        client.post(
            "/api/game/action",
            json={"kind": "begin_interview", "character_id": "inspector_elena_hayes"},
        )
        response = client.post(
            "/api/game/action",
            json={"kind": "interview_exchange", "message": "Where were you?"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["accepted"] is True
        assert payload["portrayal"]["source"] == "fallback"
        assert payload["portrayal"]["surface_utterance"] == payload["dialogue"]["text"]


def test_invalid_interview_text_is_rejected_before_engine_mutates(tmp_path):
    with _client(tmp_path) as client:
        client.post("/api/game/demo", json={})
        client.post("/api/game/action", json={"kind": "advance_opening"})
        client.post(
            "/api/game/action",
            json={"kind": "begin_interview", "character_id": "inspector_elena_hayes"},
        )
        before = client.get("/api/game/state").json()
        for message in ("   ", "x" * 1201):
            rejected = client.post(
                "/api/game/action",
                json={"kind": "interview_exchange", "message": message},
            )
            assert rejected.status_code == 422
        after = client.get("/api/game/state").json()

        assert after["turn"] == before["turn"]
        assert after["in_game_minute"] == before["in_game_minute"]
        assert after["active_interview_exchanges_remaining"] == before["active_interview_exchanges_remaining"]
        assert after["statements"] == before["statements"]
