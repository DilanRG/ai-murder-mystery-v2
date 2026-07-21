"""Measured direct-DeepSeek request boundary for the V4 experiment."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from llm.client import LLMClient, LLMMessage, LLMProviderError, LLMResponse
from llm.experiment import (
    BudgetStop,
    DeepSeekExperimentLedger,
    ExperimentPolicyError,
    LedgerIntegrityError,
    Reservation,
)

from experiments.deepseek_v4_runner import (
    EXPECTED_MODELS,
    PRIVATE_ARTIFACT_ROOT,
    ExperimentSafetyError,
    model_resolution_matches,
)

DIRECT_PRICING_USD_PER_MILLION = {
    "deepseek-v4-flash": {
        "cache_hit_input": Decimal("0.0028"),
        "cache_miss_input": Decimal("0.14"),
        "output": Decimal("0.28"),
    },
    "deepseek-v4-pro": {
        "cache_hit_input": Decimal("0.003625"),
        "cache_miss_input": Decimal("0.435"),
        "output": Decimal("0.87"),
    },
}
DIRECT_API_KEY_PATH = PRIVATE_ARTIFACT_ROOT / "direct_api_key.txt"


def load_direct_api_key() -> str:
    """Load the ignored direct credential without exposing it to committed config."""

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key and DIRECT_API_KEY_PATH.is_file():
        api_key = DIRECT_API_KEY_PATH.read_text(encoding="utf-8").strip()
    if not api_key or any(character.isspace() for character in api_key):
        raise ExperimentSafetyError("Configure a valid direct DeepSeek credential locally.")
    return api_key


@dataclass(frozen=True)
class RunContext:
    experiment_revision: int
    git_sha: str
    run_id: str
    phase: str
    pair_id: str = ""
    case_fingerprint: str = ""


class DeepSeekRequestObserver:
    """Reserve, verify, settle, and record every measured model request."""

    def __init__(
        self,
        *,
        ledger: DeepSeekExperimentLedger,
        metrics_path: Path,
        context: RunContext,
    ) -> None:
        self.ledger = ledger
        self.metrics_path = metrics_path
        self.context = context
        self._reservations: dict[str, Reservation] = {}
        self._lock = threading.Lock()
        self.last_record: dict[str, Any] | None = None
        self.records: list[dict[str, Any]] = []

    async def __call__(self, event: str, data: dict[str, Any]) -> None:
        if event == "pre_call":
            self._reserve(data)
            return
        if event != "response":
            raise ExperimentSafetyError("Unknown request-observer event.")
        await self._settle_or_record_failure(data)

    def _reserve(self, data: Mapping[str, Any]) -> None:
        request_id = str(data.get("request_id", ""))
        model = str(data.get("model", ""))
        if model not in EXPECTED_MODELS.values():
            raise ExperimentSafetyError("Measured request used an unapproved model slug.")
        if data.get("transport") != "deepseek_direct" or data.get("provider_routing") is not None:
            raise ExperimentSafetyError("Measured request was not pinned to direct DeepSeek.")
        if data.get("reasoning_effort") != "high":
            raise ExperimentSafetyError("Measured request did not use high reasoning effort.")
        reservation = self.ledger.reserve(
            provider="deepseek",
            model=model,  # type: ignore[arg-type]
            prompt_tokens_upper_bound=int(data.get("prompt_tokens_upper_bound", 0)),
            max_output_tokens=int(data.get("max_tokens", 0)),
            parameters={"transport": "deepseek_direct", "thinking": "enabled"},
            reasoning="high",
            allow_fallbacks=False,
        )
        self._reservations[request_id] = reservation

    async def _settle_or_record_failure(self, data: Mapping[str, Any]) -> None:
        transport_request_id = str(data.get("request_id", ""))
        reservation = self._reservations.pop(transport_request_id, None)
        if reservation is None:
            raise ExperimentSafetyError("Measured response has no budget reservation.")
        response = data.get("response")
        error = data.get("error")
        if not isinstance(response, LLMResponse):
            record = self._base_record(data, reservation) | {
                "result": "cancelled" if data.get("cancelled") else "provider_error",
                "error_type": type(error).__name__ if error is not None else "unknown",
                "accounting_status": "reservation_retained",
            }
            self._append_record(record)
            return
        if not response.id:
            self._append_record(
                self._base_record(data, reservation)
                | {
                    "result": "unverified_response",
                    "accounting_status": "reservation_retained",
                }
            )
            raise ExperimentSafetyError("Direct DeepSeek generation ID is unavailable.")

        provider = "deepseek"
        actual_model = response.model
        fallback_used = not model_resolution_matches(reservation.model, actual_model)
        if fallback_used or provider != "deepseek":
            self._append_record(
                self._base_record(data, reservation)
                | {
                    "generation_id": response.id,
                    "actual_model": actual_model,
                    "upstream_provider": provider,
                    "transport": str(data.get("transport", "")),
                    "fallback_used": fallback_used,
                    "provider_failover_used": False,
                    "result": "direct_verification_failed",
                    "accounting_status": "reservation_retained",
                }
            )
            raise ExperimentSafetyError("Direct DeepSeek model verification failed.")

        cached_tokens = response.prompt_cached_tokens
        uncached_tokens = response.prompt_cache_miss_tokens
        usage_is_complete = (
            response.prompt_tokens > 0
            and response.completion_tokens > 0
            and cached_tokens >= 0
            and uncached_tokens >= 0
            and cached_tokens + uncached_tokens == response.prompt_tokens
            and response.reported_total_tokens
            == response.prompt_tokens + response.completion_tokens
        )
        if not usage_is_complete:
            self._append_record(
                self._base_record(data, reservation)
                | {
                    "generation_id": response.id,
                    "actual_model": actual_model,
                    "upstream_provider": provider,
                    "fallback_used": False,
                    "provider_failover_used": False,
                    "result": "accounting_unavailable",
                    "accounting_status": "reservation_retained",
                }
            )
            raise ExperimentSafetyError("Complete direct DeepSeek token accounting is required.")

        price = DIRECT_PRICING_USD_PER_MILLION[reservation.model]
        prompt_cost = (
            Decimal(cached_tokens) * price["cache_hit_input"]
            + Decimal(uncached_tokens) * price["cache_miss_input"]
        ) / Decimal(1_000_000)
        completion_cost = (
            Decimal(response.completion_tokens) * price["output"]
        ) / Decimal(1_000_000)
        settlement = self.ledger.settle(
            reservation,
            upstream_cost_usd=prompt_cost + completion_cost,
            openrouter_fee_usd="0",
            accounting_trusted=True,
        )
        record = self._base_record(data, reservation) | {
            "generation_id": response.id,
            "actual_model": actual_model,
            "upstream_provider": provider,
            "transport": "deepseek_direct",
            "is_byok": None,
            "fallback_used": False,
            "provider_failover_used": False,
            "prompt_tokens": response.prompt_tokens,
            "cached_prompt_tokens": response.prompt_cached_tokens,
            "cache_miss_prompt_tokens": response.prompt_cache_miss_tokens,
            "completion_tokens": response.completion_tokens,
            "reasoning_tokens": response.reasoning_tokens,
            "total_tokens": response.total_tokens,
            "latency_seconds": response.wall_latency_seconds,
            "provider_latency": response.latency,
            "finish_reason": response.finish_reason,
            "native_finish_reason": response.native_finish_reason,
            "upstream_inference_cost_usd": float(settlement.upstream_cost_usd),
            "upstream_prompt_cost_usd": float(prompt_cost),
            "upstream_completion_cost_usd": float(completion_cost),
            "openrouter_fee_usd": 0.0,
            "openrouter_charge_usd": None,
            "total_external_cost_usd": float(settlement.total_cost_usd),
            "result": "success",
            "accounting_status": "measured",
            "accounting_mode": "direct_token_meter",
        }
        self._append_record(record)

    def _base_record(
        self,
        data: Mapping[str, Any],
        reservation: Reservation,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "experiment_revision": self.context.experiment_revision,
            "git_sha": self.context.git_sha,
            "started_at": str(data.get("started_at", "")),
            "run_id": self.context.run_id,
            "phase": self.context.phase,
            "pair_id": self.context.pair_id,
            "case_fingerprint": self.context.case_fingerprint,
            "request_id": reservation.request_id,
            "transport_request_id": str(data.get("request_id", "")),
            "task_role": str(data.get("task_role", "")),
            "requested_model": reservation.model,
            "prompt_tokens_upper_bound": reservation.prompt_tokens_upper_bound,
            "max_output_tokens": reservation.max_output_tokens,
            "reserved_usd": float(reservation.reserved_usd),
        }

    def _append_record(self, record: dict[str, Any]) -> None:
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            with self.metrics_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
            self.last_record = dict(record)
            self.records.append(dict(record))


class SequentialMeasuredClient:
    """Serialize measured calls and latch closed after an uncertain request.

    Production NPC planning launches seven isolated coroutines together. The
    frozen experiment declares concurrency one, so this adapter queues them.
    If any transport/accounting request fails, later queued calls are refused
    locally; this prevents seven simultaneous uncertain reservations while the
    engine can still apply its deterministic per-actor fallbacks.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self._lock = asyncio.Lock()
        self.abort_code: str | None = None

    @property
    def model(self) -> str:
        return self._client.model

    @property
    def aborted(self) -> bool:
        return self.abort_code is not None

    async def generate(self, *args: Any, **kwargs: Any) -> LLMResponse:
        async with self._lock:
            if self.abort_code is not None:
                raise LLMProviderError(
                    "The measured provider session has stopped.",
                    code="experiment_session_stopped",
                    retryable=False,
                )
            try:
                return await self._client.generate(*args, **kwargs)
            except asyncio.CancelledError:
                self.abort_code = "provider_cancelled"
                raise
            except LLMProviderError as error:
                self.abort_code = error.code
                raise
            except Exception:
                self.abort_code = "experiment_runtime_error"
                raise


def build_measured_client(
    *,
    api_key: str,
    model: str,
    observer: DeepSeekRequestObserver,
) -> LLMClient:
    """Construct one exact-model client and connect its stats lookup."""

    if model not in EXPECTED_MODELS.values():
        raise ExperimentSafetyError("Only exact manifest model slugs are allowed.")

    async def fail_closed_observer(event: str, data: dict[str, Any]) -> None:
        try:
            await observer(event, data)
        except (
            ExperimentSafetyError,
            BudgetStop,
            ExperimentPolicyError,
            LedgerIntegrityError,
        ) as error:
            # The production generator retries malformed candidates, but a
            # Budget/routing/accounting failure is never a candidate-quality issue.
            # Convert it to a non-retryable provider boundary error so the
            # generator stops after the current call and the matrix aborts.
            raise LLMProviderError(
                "The measured provider safety gate stopped execution.",
                code="experiment_safety_stop",
                retryable=False,
            ) from error

    client = LLMClient(
        api_key=api_key,
        model=model,
        reasoning_effort="high",
        transport="deepseek_direct",
        temperature=0.8,
        top_p=0.95,
        top_k=None,
        max_tokens=1024,
        request_observer=fail_closed_observer,
    )
    return client


async def run_tiny_direct_preflight(client: LLMClient) -> dict[str, Any]:
    """Spend one deliberately tiny request and return sanitized evidence."""

    response = await client.generate(
        [
            LLMMessage(
                role="system",
                content="Reply with the single word OK. Do not add punctuation or explanation.",
            ),
            LLMMessage(role="user", content="OK"),
        ],
        max_tokens=8,
        temperature=0.0,
        task_role="byok_preflight",
    )
    return {
        "model": response.model,
        "generation_id": response.id,
        "content_ok": response.content.strip() == "OK",
    }


def run_preflight_sync(client: LLMClient) -> dict[str, Any]:
    return asyncio.run(run_tiny_direct_preflight(client))


# Compatibility imports retained for older internal callers; revision 4 uses
# the exact same tiny prompt through the direct DeepSeek transport.
run_tiny_byok_preflight = run_tiny_direct_preflight
run_tiny_openrouter_preflight = run_tiny_direct_preflight
