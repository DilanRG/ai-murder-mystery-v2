"""Provider-free tests for measured DeepSeek request verification."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from experiments.deepseek_v4_runner import EXPECTED_ROUTING, ExperimentSafetyError
from experiments.deepseek_v4_runtime import (
    DeepSeekRequestObserver,
    RunContext,
    SequentialMeasuredClient,
    build_measured_client,
)
from llm.client import LLMMessage, LLMProviderError, LLMResponse
from llm.experiment import DeepSeekExperimentLedger, PRO_MODEL_SLUG


def _event_base() -> dict[str, object]:
    return {
        "request_id": "transport-request",
        "started_at": "2026-07-21T00:00:00+00:00",
        "model": PRO_MODEL_SLUG,
        "task_role": "byok_preflight",
        "max_tokens": 8,
        "prompt_tokens_upper_bound": 100,
        "provider_routing": dict(EXPECTED_ROUTING),
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
    assert observer.last_record["started_at"] == "2026-07-21T00:00:00+00:00"
    assert observer.last_record["is_byok"] is True
    assert "content" not in observer.last_record
    assert observer.ledger.snapshot()["settled_usd"] > 0


def test_standard_openrouter_response_settles_inclusive_charge(tmp_path: Path) -> None:
    observer = _observer(tmp_path)

    async def stats(_generation_id: str) -> dict[str, object]:
        return {
            "model": PRO_MODEL_SLUG,
            "provider_name": "DeepSeek",
            "is_byok": False,
            "provider_responses": [],
            "total_cost": 0.003,
        }

    observer.stats_lookup = stats
    response = LLMResponse(content="OK", id="gen-2", model=PRO_MODEL_SLUG)

    async def run() -> None:
        base = _event_base()
        await observer("pre_call", dict(base))
        await observer(
            "response",
            dict(base) | {"response": response, "error": None, "cancelled": False},
        )

    asyncio.run(run())
    assert observer.last_record is not None
    assert observer.last_record["result"] == "success"
    assert observer.last_record["accounting_mode"] == "openrouter"
    assert observer.last_record["openrouter_charge_usd"] == 0.003
    assert observer.ledger.snapshot()["open_reservations"] == 0


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

    async def substituted_model_stats(_generation_id: str) -> dict[str, object]:
        return {
            "model": "deepseek/deepseek-v4-flash",
            "provider_name": "DeepSeek",
            "is_byok": False,
            "provider_responses": [],
            "total_cost": 0.001,
        }

    async def fake_post(_payload) -> LLMResponse:
        return LLMResponse(content="OK", id="gen-3", model=PRO_MODEL_SLUG)

    observer.stats_lookup = substituted_model_stats
    monkeypatch.setattr(client, "_post", fake_post)

    async def run() -> None:
        with pytest.raises(LLMProviderError) as caught:
            await client.generate([LLMMessage(role="user", content="OK")], max_tokens=8)
        assert caught.value.code == "experiment_safety_stop"
        assert caught.value.retryable is False

    asyncio.run(run())
    assert observer.records[-1]["result"] == "model_verification_failed"


def test_sequential_measured_client_serializes_and_latches_provider_failure() -> None:
    class Inner:
        model = PRO_MODEL_SLUG

        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0
            self.calls = 0

        async def generate(self, value: int) -> LLMResponse:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls += 1
            await asyncio.sleep(0)
            self.active -= 1
            if value == 2:
                raise LLMProviderError(
                    "provider failed",
                    code="provider_unavailable",
                    retryable=True,
                )
            return LLMResponse(content=str(value), model=self.model)

    inner = Inner()
    client = SequentialMeasuredClient(inner)  # type: ignore[arg-type]

    async def run() -> list[object]:
        return await asyncio.gather(
            client.generate(1),
            client.generate(2),
            client.generate(3),
            return_exceptions=True,
        )

    results = asyncio.run(run())
    assert inner.max_active == 1
    assert inner.calls == 2
    assert isinstance(results[0], LLMResponse)
    assert isinstance(results[1], LLMProviderError)
    assert isinstance(results[2], LLMProviderError)
    assert client.abort_code == "provider_unavailable"
