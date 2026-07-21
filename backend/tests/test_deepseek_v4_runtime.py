"""Provider-free tests for measured DeepSeek request verification."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from experiments.deepseek_v4_runner import ExperimentSafetyError
from experiments.deepseek_v4_runtime import (
    DeepSeekRequestObserver,
    RunContext,
    build_measured_client,
)
from llm.client import LLMMessage, LLMProviderError, LLMResponse
from llm.experiment import DeepSeekExperimentLedger, PRO_MODEL_SLUG


def _event_base() -> dict[str, object]:
    return {
        "request_id": "transport-request",
        "model": PRO_MODEL_SLUG,
        "task_role": "byok_preflight",
        "max_tokens": 8,
        "prompt_tokens_upper_bound": 100,
        "provider_routing": {
            "only": ["deepseek"],
            "allow_fallbacks": False,
            "require_parameters": True,
        },
        "reasoning_effort": "high",
    }


def _observer(tmp_path: Path) -> DeepSeekRequestObserver:
    return DeepSeekRequestObserver(
        ledger=DeepSeekExperimentLedger(tmp_path / "ledger.jsonl"),
        metrics_path=tmp_path / "requests.jsonl",
        context=RunContext(1, "sha", "run", "preflight"),
    )


def test_verified_response_is_settled_and_sanitized(tmp_path: Path) -> None:
    observer = _observer(tmp_path)

    async def stats(_generation_id: str) -> dict[str, object]:
        return {
            "model": PRO_MODEL_SLUG,
            "provider_name": "DeepSeek",
            "is_byok": True,
            "total_cost": 0.001,
            "upstream_inference_cost": 0.002,
            "provider_responses": [],
        }

    observer.stats_lookup = stats
    response = LLMResponse(
        content="OK",
        id="gen-1",
        model=PRO_MODEL_SLUG,
        provider="DeepSeek",
        prompt_tokens=10,
        completion_tokens=1,
        reported_total_tokens=11,
        is_byok=True,
        cost=0.001,
        cost_details={"upstream_inference_cost": 0.002},
    )

    async def run() -> None:
        base = _event_base()
        await observer("pre_call", dict(base))
        await observer("response", dict(base) | {"response": response, "error": None, "cancelled": False})

    asyncio.run(run())
    assert observer.last_record is not None
    assert observer.last_record["result"] == "success"
    assert observer.last_record["is_byok"] is True
    assert "content" not in observer.last_record
    assert observer.ledger.snapshot()["settled_usd"] > 0


def test_non_byok_response_stops_and_retains_reservation(tmp_path: Path) -> None:
    observer = _observer(tmp_path)

    async def stats(_generation_id: str) -> dict[str, object]:
        return {
            "model": PRO_MODEL_SLUG,
            "provider_name": "DeepSeek",
            "is_byok": False,
            "provider_responses": [],
        }

    observer.stats_lookup = stats
    response = LLMResponse(content="OK", id="gen-2", model=PRO_MODEL_SLUG)

    async def run() -> None:
        base = _event_base()
        await observer("pre_call", dict(base))
        with pytest.raises(ExperimentSafetyError, match="BYOK"):
            await observer(
                "response",
                dict(base) | {"response": response, "error": None, "cancelled": False},
            )

    asyncio.run(run())
    assert observer.last_record is not None
    assert observer.last_record["result"] == "byok_verification_failed"
    assert observer.ledger.snapshot()["open_reservations"] == 1


def test_measured_client_exposes_safety_stop_as_non_retryable_provider_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = _observer(tmp_path)
    client = build_measured_client(
        api_key="test-gateway-credential",
        model=PRO_MODEL_SLUG,
        observer=observer,
    )

    async def non_byok_stats(_generation_id: str) -> dict[str, object]:
        return {
            "model": PRO_MODEL_SLUG,
            "provider_name": "DeepSeek",
            "is_byok": False,
            "provider_responses": [],
        }

    async def fake_post(_payload) -> LLMResponse:
        return LLMResponse(content="OK", id="gen-3", model=PRO_MODEL_SLUG)

    observer.stats_lookup = non_byok_stats
    monkeypatch.setattr(client, "_post", fake_post)

    async def run() -> None:
        with pytest.raises(LLMProviderError) as caught:
            await client.generate([LLMMessage(role="user", content="OK")], max_tokens=8)
        assert caught.value.code == "experiment_safety_stop"
        assert caught.value.retryable is False

    asyncio.run(run())
    assert observer.records[-1]["result"] == "byok_verification_failed"
