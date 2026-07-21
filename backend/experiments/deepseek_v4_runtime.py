"""Measured OpenRouter request boundary for the DeepSeek V4 experiment."""

from __future__ import annotations

import asyncio
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

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
    EXPECTED_ROUTING,
    ExperimentSafetyError,
)


StatsLookup = Callable[[str], Awaitable[dict[str, Any]]]


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
        self.stats_lookup: StatsLookup | None = None
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
        routing = data.get("provider_routing")
        if model not in EXPECTED_MODELS.values():
            raise ExperimentSafetyError("Measured request used an unapproved model slug.")
        if routing != EXPECTED_ROUTING:
            raise ExperimentSafetyError("Measured request was not pinned to OpenRouter routing.")
        if data.get("reasoning_effort") != "high":
            raise ExperimentSafetyError("Measured request did not use high reasoning effort.")
        reservation = self.ledger.reserve(
            provider="openrouter",
            model=model,  # type: ignore[arg-type]
            prompt_tokens_upper_bound=int(data.get("prompt_tokens_upper_bound", 0)),
            max_output_tokens=int(data.get("max_tokens", 0)),
            parameters=dict(routing),
            reasoning="high",
            allow_fallbacks=True,
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
        if not response.id or self.stats_lookup is None:
            self._append_record(
                self._base_record(data, reservation)
                | {
                    "result": "unverified_response",
                    "accounting_status": "reservation_retained",
                }
            )
            raise ExperimentSafetyError("Generation ID or statistics lookup is unavailable.")

        stats = await self.stats_lookup(response.id)
        provider = str(stats.get("provider_name") or response.provider).casefold()
        actual_model = str(stats.get("model") or response.model)
        is_byok = stats.get("is_byok") if stats.get("is_byok") is not None else response.is_byok
        provider_responses = stats.get("provider_responses") or []
        provider_attempts = {
            str(item.get("provider_name", "")).strip().casefold()
            for item in provider_responses
            if isinstance(item, Mapping) and str(item.get("provider_name", "")).strip()
        }
        provider_failover_used = len(provider_attempts) > 1
        fallback_used = actual_model != reservation.model
        if fallback_used or not provider:
            self._append_record(
                self._base_record(data, reservation)
                | {
                    "generation_id": response.id,
                    "actual_model": actual_model,
                    "upstream_provider": provider,
                    "is_byok": is_byok,
                    "fallback_used": fallback_used,
                    "provider_failover_used": provider_failover_used,
                    "result": "model_verification_failed",
                    "accounting_status": "reservation_retained",
                }
            )
            raise ExperimentSafetyError("OpenRouter exact-model verification failed.")

        upstream_cost = response.cost_details.get("upstream_inference_cost")
        upstream_prompt_cost = response.cost_details.get(
            "upstream_inference_prompt_cost"
        )
        upstream_completion_cost = response.cost_details.get(
            "upstream_inference_completions_cost"
        )
        if upstream_cost is None and (
            upstream_prompt_cost is not None and upstream_completion_cost is not None
        ):
            try:
                upstream_cost = float(upstream_prompt_cost) + float(upstream_completion_cost)
            except (TypeError, ValueError):
                upstream_cost = None
        if upstream_cost is None:
            upstream_cost = stats.get("upstream_inference_cost")
        openrouter_charge = response.cost
        if openrouter_charge is None:
            openrouter_charge = stats.get("total_cost")
        if openrouter_charge is None or (is_byok is True and upstream_cost is None):
            self._append_record(
                self._base_record(data, reservation)
                | {
                    "generation_id": response.id,
                    "actual_model": actual_model,
                    "upstream_provider": provider,
                    "is_byok": is_byok,
                    "fallback_used": False,
                    "provider_failover_used": provider_failover_used,
                    "result": "accounting_unavailable",
                    "accounting_status": "reservation_retained",
                }
            )
            raise ExperimentSafetyError("Trusted OpenRouter accounting is required.")

        if is_byok is True:
            settlement = self.ledger.settle(
                reservation,
                upstream_cost_usd=upstream_cost,
                openrouter_fee_usd=openrouter_charge,
                accounting_trusted=True,
            )
            accounting_mode = "byok"
            measured_upstream_cost = float(settlement.upstream_cost_usd)
            measured_openrouter_fee = float(settlement.openrouter_fee_usd)
            measured_openrouter_charge = None
        else:
            settlement = self.ledger.settle_openrouter_charge(
                reservation,
                openrouter_charge_usd=openrouter_charge,
                accounting_trusted=True,
            )
            accounting_mode = "openrouter"
            measured_upstream_cost = self._safe_optional_cost(upstream_cost)
            measured_openrouter_fee = None
            measured_openrouter_charge = float(settlement.total_cost_usd)
        record = self._base_record(data, reservation) | {
            "generation_id": response.id,
            "actual_model": actual_model,
            "upstream_provider": provider,
            "is_byok": is_byok,
            "fallback_used": False,
            "provider_failover_used": provider_failover_used,
            "prompt_tokens": response.prompt_tokens,
            "cached_prompt_tokens": response.prompt_cached_tokens,
            "completion_tokens": response.completion_tokens,
            "reasoning_tokens": response.reasoning_tokens,
            "total_tokens": response.total_tokens,
            "latency_seconds": response.wall_latency_seconds,
            "provider_latency": response.latency,
            "finish_reason": response.finish_reason,
            "native_finish_reason": response.native_finish_reason,
            "upstream_inference_cost_usd": measured_upstream_cost,
            "upstream_prompt_cost_usd": self._safe_optional_cost(
                upstream_prompt_cost
            ),
            "upstream_completion_cost_usd": self._safe_optional_cost(
                upstream_completion_cost
            ),
            "openrouter_fee_usd": measured_openrouter_fee,
            "openrouter_charge_usd": measured_openrouter_charge,
            "total_external_cost_usd": float(settlement.total_cost_usd),
            "result": "success",
            "accounting_status": "measured",
            "accounting_mode": accounting_mode,
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

    @staticmethod
    def _safe_optional_cost(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) and parsed >= 0 else None

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
        provider_routing=EXPECTED_ROUTING,
        reasoning_effort="high",
        temperature=0.8,
        top_p=0.95,
        top_k=40,
        max_tokens=1024,
        request_observer=fail_closed_observer,
    )
    observer.stats_lookup = client.query_generation_stats
    return client


async def run_tiny_openrouter_preflight(client: LLMClient) -> dict[str, Any]:
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
    return asyncio.run(run_tiny_openrouter_preflight(client))


# Compatibility import for the already committed opt-in runner. Revision 2
# verifies OpenRouter exact-model/accounting evidence rather than requiring a
# direct-provider BYOK route.
run_tiny_byok_preflight = run_tiny_openrouter_preflight
