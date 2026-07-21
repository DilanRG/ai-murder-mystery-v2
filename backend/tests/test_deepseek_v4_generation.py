"""Offline production-path tests for the paid paired-generation runner."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import uuid

import pytest

from conftest import make_dummy_generated_document
from experiments.run_deepseek_v4_generation import run_generation_matrix
from experiments.deepseek_v4_runner import (
    EXPECTED_MODELS,
    EXPECTED_ROUTING,
    ExperimentSafetyError,
    load_manifest,
)
from llm.client import LLMResponse


GIT_SHA = "b" * 40


def _preflights() -> dict[str, object]:
    return {
        key: {
            "experiment_revision": 2,
            "git_sha": GIT_SHA,
            "model": model,
            "upstream_provider": "openrouter-provider",
            "is_byok": False,
            "fallback_used": False,
            "accounting_mode": "openrouter",
            "generation_id": f"preflight-{key}",
            "total_external_cost_usd": 0.001,
        }
        for key, model in EXPECTED_MODELS.items()
    }


class _OfflineMeasuredClient:
    def __init__(self, *, model: str, observer, content_factory) -> None:
        self.model = model
        self.observer = observer
        self.content_factory = content_factory
        self.calls = 0
        observer.stats_lookup = self._stats

    async def _stats(self, generation_id: str) -> dict[str, object]:
        return {
            "id": generation_id,
            "model": self.model,
            "provider_name": "DeepSeek",
            "is_byok": True,
            "provider_responses": [{"provider_name": "DeepSeek"}],
            "total_cost": 0.00001,
            "upstream_inference_cost": 0.0001,
        }

    async def generate(self, messages, **kwargs) -> LLMResponse:
        assert kwargs["task_role"] == "case_generation"
        self.calls += 1
        transport_request_id = uuid.uuid4().hex
        event = {
            "request_id": transport_request_id,
            "model": self.model,
            "task_role": kwargs["task_role"],
            "max_tokens": kwargs["max_tokens"],
            "prompt_tokens_upper_bound": sum(len(message.content) for message in messages),
            "provider_routing": dict(EXPECTED_ROUTING),
            "reasoning_effort": "high",
        }
        await self.observer("pre_call", event)
        content = self.content_factory(messages)
        if not isinstance(content, str):
            content = json.dumps(content)
        response = LLMResponse(
            content=content,
            id=f"generation-{uuid.uuid4().hex}",
            model=self.model,
            provider="DeepSeek",
            prompt_tokens=100,
            completion_tokens=200,
            reasoning_tokens=50,
            cost=0.00001,
            cost_details={"upstream_inference_cost": 0.0001},
            wall_latency_seconds=0.01,
        )
        await self.observer(
            "response",
            {
                **event,
                "response": response,
                "error": None,
                "cancelled": False,
            },
        )
        return response


def test_generation_matrix_uses_production_admission_and_private_snapshots(
    tmp_path: Path,
) -> None:
    manifest = load_manifest()
    pair = manifest["generation_pairs"][0]

    def client_builder(*, api_key, model, observer):
        assert api_key == "test-gateway-credential"

        def content_factory(_messages):
            return make_dummy_generated_document(character_ids=tuple(pair["cast_ids"]))

        return _OfflineMeasuredClient(
            model=model,
            observer=observer,
            content_factory=content_factory,
        )

    outcomes = asyncio.run(
        run_generation_matrix(
            manifest=manifest,
            preflight_evidence=_preflights(),
            git_sha=GIT_SHA,
            api_key="test-gateway-credential",
            artifact_root=tmp_path,
            explicitly_enabled=True,
            client_builder=client_builder,
            pairs=[pair],
        )
    )

    assert [outcome["model_key"] for outcome in outcomes] == pair["model_order"]
    assert all(outcome["admitted"] is True for outcome in outcomes)
    assert all(outcome["attempts"] == 1 for outcome in outcomes)
    assert all(len(outcome["case_fingerprint"]) == 64 for outcome in outcomes)
    assert all((tmp_path / outcome["canonical_artifact"]).is_file() for outcome in outcomes)
    progress = json.loads((tmp_path / "generation_results.json").read_text(encoding="utf-8"))
    assert len(progress["outcomes"]) == 2
    request_records = (tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(request_records) == 2
    assert all(json.loads(record)["task_role"] == "case_generation" for record in request_records)
    attempts = [
        json.loads(record)
        for record in (tmp_path / "generation_attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(attempts) == 2
    assert all(record["admission_result"] == "admitted" for record in attempts)
    assert all(record["request_id"] and record["generation_id"] for record in attempts)


def test_generation_matrix_counts_three_rejected_candidates_without_outer_retry(
    tmp_path: Path,
) -> None:
    manifest = load_manifest()
    pair = manifest["generation_pairs"][0]

    def client_builder(*, api_key, model, observer):
        del api_key
        return _OfflineMeasuredClient(
            model=model,
            observer=observer,
            content_factory=lambda _messages: "{not-json",
        )

    outcomes = asyncio.run(
        run_generation_matrix(
            manifest=manifest,
            preflight_evidence=_preflights(),
            git_sha=GIT_SHA,
            api_key="test-gateway-credential",
            artifact_root=tmp_path,
            explicitly_enabled=True,
            client_builder=client_builder,
            pairs=[pair],
        )
    )

    assert len(outcomes) == 2
    assert all(outcome["admitted"] is False for outcome in outcomes)
    assert all(outcome["attempts"] == 3 for outcome in outcomes)
    assert all(outcome["failure_code"] == "invalid_generated_case" for outcome in outcomes)
    assert len((tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()) == 6
    attempts = [
        json.loads(record)
        for record in (tmp_path / "generation_attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(attempts) == 6
    assert all(record["failure_category"] == "malformed_json" for record in attempts)
    assert [record["repair_feedback_used"] for record in attempts[:3]] == [False, True, True]


def test_generation_matrix_refuses_unverified_revision_before_building_client(
    tmp_path: Path,
) -> None:
    manifest = load_manifest()
    built = False

    def client_builder(**_kwargs):
        nonlocal built
        built = True

    with pytest.raises(ExperimentSafetyError, match="different code revision"):
        asyncio.run(
            run_generation_matrix(
                manifest=manifest,
                preflight_evidence=_preflights(),
                git_sha="c" * 40,
                api_key="test-gateway-credential",
                artifact_root=tmp_path,
                explicitly_enabled=True,
                client_builder=client_builder,
                pairs=[manifest["generation_pairs"][0]],
            )
        )
    assert built is False
