"""Provider-required New Story and explicit offline-demo contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from conftest import generated_stage_response, make_dummy_generated_document
from game.case_generation import select_generation_cast
from game.content import CHARACTER_CARDS_DIR, list_content_ids, load_case
from game.models import CaseDefinition
from game.recipes import case_content_fingerprint
from llm.client import LLMClient
from llm.client import LLMProviderError


class DummyScenarioProvider:
    def __init__(self, outputs: list[dict[str, object] | Exception]) -> None:
        self.outputs = list(outputs)
        self.calls = 0
        self.document: dict[str, object] | None = None

    async def generate(self, messages, **kwargs):
        self.calls += 1
        if self.document is not None and kwargs.get("task_role", "").startswith(
            "case_generation_"
        ):
            output: dict[str, object] | Exception = generated_stage_response(
                self.document, kwargs["task_role"]
            )
        else:
            output = self.outputs.pop(0) if self.outputs else {}
        if isinstance(output, Exception):
            raise output
        if "case" in output and "presentation" in output:
            self.document = output
            output = generated_stage_response(output, kwargs["task_role"])
        return SimpleNamespace(content=json.dumps(output))


def _client(tmp_path) -> TestClient:
    main._session.engine = None
    main._session.llm = None
    main._session.save_root = tmp_path
    return TestClient(main.app)


def test_normal_new_story_requires_provider_and_preserves_active_demo(tmp_path) -> None:
    with _client(tmp_path) as client:
        demo = client.post("/api/game/demo", json={})
        assert demo.status_code == 200
        previous_case_id = main._session.engine.case.id
        main._session.llm = None

        response = client.post("/api/game/new", json={"seed": 7})

        assert response.status_code == 428
        assert response.json()["detail"]["code"] == "provider_not_configured"
        assert main._session.engine.case.id == previous_case_id


def test_normal_new_story_admits_dummy_provider_case_with_exact_manual_cast(tmp_path) -> None:
    source = load_case("ashwick_sample")
    provider = DummyScenarioProvider([make_dummy_generated_document()])
    with _client(tmp_path) as client:
        main._session.llm = provider
        response = client.post(
            "/api/game/new",
            json={
                "seed": 84,
                "location_id": "ashwick_manor",
                "character_ids": list(source.character_ids),
                "difficulty": "normal",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "case_id" not in payload["game"]
    assert main._session.engine.case.id.startswith("generated_")
    assert payload["generation"] == {
        "mode": "generated",
        "seed": 84,
        "cast_mode": "manual",
        "location_id": "ashwick_manor",
        "story_source": "openrouter",
        "story_status": "ready",
    }
    assert provider.calls == 4
    assert set(main._session.engine.case.character_ids) == set(source.character_ids)


def test_rejected_provider_case_never_replaces_existing_demo(tmp_path) -> None:
    provider = DummyScenarioProvider([{}, {}, {}])
    with _client(tmp_path) as client:
        assert client.post("/api/game/demo", json={}).status_code == 200
        previous_engine = main._session.engine
        main._session.llm = provider

        response = client.post(
            "/api/game/new",
            json={
                "seed": 3,
                "character_ids": list(previous_engine.case.character_ids),
            },
        )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_generated_case"
    assert main._session.engine is previous_engine
    assert provider.calls == 3


def test_provider_auth_failure_is_sanitized_and_not_retried(tmp_path) -> None:
    provider = DummyScenarioProvider(
        [
            LLMProviderError(
                "secret upstream response",
                code="provider_auth_failed",
                status_code=401,
                retryable=False,
            )
        ]
    )
    with _client(tmp_path) as client:
        assert client.post("/api/game/demo", json={}).status_code == 200
        previous_engine = main._session.engine
        main._session.llm = provider

        response = client.post("/api/game/new", json={"seed": 4})

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "provider_auth_failed",
        "message": "OpenRouter rejected the stored API key. Update it in Settings.",
    }
    assert "secret upstream response" not in response.text
    assert provider.calls == 1
    assert main._session.engine is previous_engine


def test_settings_reject_minus_million_and_unknown_provider_fields(tmp_path) -> None:
    with _client(tmp_path) as client:
        for payload in (
            {"temperature": -1},
            {"top_p": 1_000_000},
            {"max_tokens": -1},
            {"max_tokens": 1_000_000},
            {"api_key": "short"},
            {"provider_patch": {"api_key": "leak"}},
        ):
            assert client.post("/api/settings", json=payload).status_code == 422


def test_model_catalog_failure_never_echoes_provider_exception(
    tmp_path, monkeypatch
) -> None:
    async def fail_safely(api_key: str):
        raise RuntimeError("secret provider body with sk-never-echo-this")

    monkeypatch.setattr(LLMClient, "fetch_models", fail_safely)
    with _client(tmp_path) as client:
        response = client.get("/api/models")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not fetch OpenRouter models."
    assert "secret provider body" not in response.text
    assert "sk-never-echo-this" not in response.text


def test_offline_demo_never_calls_configured_provider(tmp_path) -> None:
    provider = DummyScenarioProvider([make_dummy_generated_document()])
    with _client(tmp_path) as client:
        main._session.llm = provider
        response = client.post(
            "/api/game/demo",
            json={"recipe_id": "ashwick_manor_dual_spines", "seed": 42},
        )

    assert response.status_code == 200
    assert response.json()["recipe"]["story_source"] == "fallback"
    assert provider.calls == 0


def test_generated_cast_selection_uses_any_eight_of_full_pool() -> None:
    pool = tuple(list_content_ids(CHARACTER_CARDS_DIR))
    arbitrary_manual_cast = tuple(pool[::3][:8])

    manual = select_generation_cast(seed=12, character_ids=arbitrary_manual_cast)
    first = select_generation_cast(seed=999)
    repeated = select_generation_cast(seed=999)
    different = select_generation_cast(seed=1_000)

    assert len(pool) == 24
    assert manual == arbitrary_manual_cast
    assert first == repeated
    assert first != different
    assert len(first) == len(set(first)) == 8
    assert set(first) <= set(pool)


def test_generated_case_save_load_embeds_validated_truth_without_provider_key(tmp_path) -> None:
    source = load_case("ashwick_sample")
    provider = DummyScenarioProvider([make_dummy_generated_document()])
    with _client(tmp_path) as client:
        main._session.llm = provider
        started = client.post(
            "/api/game/new",
            json={"seed": 84, "character_ids": list(source.character_ids)},
        )
        assert started.status_code == 200
        generated_case_id = main._session.engine.case.id
        saved = client.post(
            "/api/game/saves/v2",
            json={"filename": "generated-round-trip"},
        )
        assert saved.status_code == 200
        document = json.loads((tmp_path / "generated-round-trip.json").read_text())
        assert document["generated_case"]["id"] == generated_case_id
        assert document["generated_case_fingerprint"]
        assert "api_key" not in json.dumps(document).lower()

        assert client.post("/api/game/demo", json={}).status_code == 200
        loaded = client.post(
            "/api/game/saves/v2/generated-round-trip.json/load"
        )

    assert loaded.status_code == 200, loaded.text
    assert main._session.engine.case.id == generated_case_id
    assert main._session.engine.case.id.startswith("generated_")
    assert provider.calls == 4


def test_generated_case_save_rejects_embedded_truth_tampering(tmp_path) -> None:
    source = load_case("ashwick_sample")
    provider = DummyScenarioProvider([make_dummy_generated_document()])
    with _client(tmp_path) as client:
        main._session.llm = provider
        assert client.post(
            "/api/game/new",
            json={"seed": 84, "character_ids": list(source.character_ids)},
        ).status_code == 200
        assert client.post(
            "/api/game/saves/v2",
            json={"filename": "tampered-generated"},
        ).status_code == 200
        path = tmp_path / "tampered-generated.json"
        document = json.loads(path.read_text())
        document["generated_case"]["title"] = "Tampered truth"
        path.write_text(json.dumps(document), encoding="utf-8")

        response = client.post(
            "/api/game/saves/v2/tampered-generated.json/load"
        )

    assert response.status_code == 400
    assert "fingerprint" in response.json()["detail"].lower()


def test_generated_case_save_revalidates_refingerprinted_truth(tmp_path) -> None:
    source = load_case("ashwick_sample")
    provider = DummyScenarioProvider([make_dummy_generated_document()])
    with _client(tmp_path) as client:
        main._session.llm = provider
        assert client.post(
            "/api/game/new",
            json={"seed": 84, "character_ids": list(source.character_ids)},
        ).status_code == 200
        assert client.post(
            "/api/game/saves/v2",
            json={"filename": "refingerprinted-generated"},
        ).status_code == 200
        path = tmp_path / "refingerprinted-generated.json"
        document = json.loads(path.read_text())
        generated_case = document["generated_case"]
        generated_case["murder"]["minute"] = generated_case["opening"][
            "discovery_minute"
        ]
        invalid_truth = CaseDefinition.model_validate(generated_case)
        document["generated_case_fingerprint"] = case_content_fingerprint(invalid_truth)
        path.write_text(json.dumps(document), encoding="utf-8")

        response = client.post(
            "/api/game/saves/v2/refingerprinted-generated.json/load"
        )

    assert response.status_code == 400
    assert "generated case" in response.json()["detail"].lower()
