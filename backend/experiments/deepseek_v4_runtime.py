"""Measured DeepSeek-only request boundary for the Phase 1 experiment."""

from __future__ import annotations

import asyncio
import json
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
            raise ExperimentSafetyError("Measured request was not pinned to DeepSeek-only routing.")
        if data.get("reasoning_effort") != "high":
            raise ExperimentSafetyError("Measured request did not use high reasoning effort.")
        reservation = self.ledger.reserve(
            provider="deepseek",
            model=model,  # type: ignore[arg-type]
            prompt_tokens_upper_bound=int(data.get("prompt_tokens_upper_bound", 0)),
            max_output_tokens=int(data.get("max_tokens", 0)),
            parameters=dict(routing),
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
        fallback_used = any(
            str(item.get("provider_name", "")).casefold() not in {"", "deepseek"}
            for item in provider_responses
            if isinstance(item, Mapping)
        )
        if (
            actual_model != reservation.model
            or provider != "deepseek"
            or is_byok is not True
            or fallback_used
        ):
            self._append_record(
                self._base_record(data, reservation)
                | {
                    "generation_id": response.id,
                    "actual_model": actual_model,
                    "upstream_provider": provider,
                    "is_byok": is_byok,
                    "fallback_used": fallback_used,
                    "result": "byok_verification_failed",
                    "accounting_status": "reservation_retained",
                }
            )
            raise ExperimentSafetyError("DeepSeek BYOK endpoint verification failed.")

        upstream_cost = response.cost_details.get("upstream_inference_cost")
        if upstream_cost is None:
            upstream_cost = stats.get("upstream_inference_cost")
        openrouter_fee = response.cost
        if openrouter_fee is None:
            openrouter_fee = stats.get("total_cost")
        if upstream_cost is None or openrouter_fee is None:
            self._append_record(
                self._base_record(data, reservation)
                | {
                    "generation_id": response.id,
                    "actual_model": actual_model,
                    "upstream_provider": provider,
                    "is_byok": True,
                    "fallback_used": False,
                    "result": "accounting_unavailable",
                    "accounting_status": "reservation_retained",
                }
            )
            raise ExperimentSafetyError("Trusted upstream and OpenRouter accounting are required.")

        settlement = self.ledger.settle(
            reservation,
            upstream_cost_usd=upstream_cost,
            openrouter_fee_usd=openrouter_fee,
            accounting_trusted=True,
        )
        record = self._base_record(data, reservation) | {
            "generation_id": response.id,
            "actual_model": actual_model,
            "upstream_provider": provider,
            "is_byok": True,
            "fallback_used": False,
            "prompt_tokens": response.prompt_tokens,
            "cached_prompt_tokens": response.prompt_cached_tokens,
            "completion_tokens": response.completion_tokens,
            "reasoning_tokens": response.reasoning_tokens,
            "total_tokens": response.total_tokens,
            "latency_seconds": response.wall_latency_seconds,
            "provider_latency": response.latency,
            "finish_reason": response.finish_reason,
            "native_finish_reason": response.native_finish_reason,
            "upstream_inference_cost_usd": float(settlement.upstream_cost_usd),
            "openrouter_fee_usd": float(settlement.openrouter_fee_usd),
            "total_external_cost_usd": float(settlement.total_cost_usd),
            "result": "success",
            "accounting_status": "measured",
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
            # budget/BYOK/accounting failure is never a candidate-quality issue.
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


async def run_tiny_byok_preflight(client: LLMClient) -> dict[str, Any]:
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
    return asyncio.run(run_tiny_byok_preflight(client))
