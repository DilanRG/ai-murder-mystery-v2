"""
OpenRouter LLM client with tool-calling support.
Handles all LLM interactions for both story generation and agent loops.
"""
import json
import logging
import asyncio
import inspect
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from config.settings import OPENROUTER_BASE_URL


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_SUPPORTED_TRANSPORTS = {"openrouter", "deepseek_direct"}

logger = logging.getLogger(__name__)


RequestObserver = Callable[[str, dict[str, Any]], Awaitable[None] | None]
"""Receives ``pre_call`` and ``response`` request lifecycle events.

Observers are deliberately passed no headers, so accounting integrations never
need to handle an API key.  A ``pre_call`` observer can reserve a budget by
raising; the provider request is then not made.  Every successful pre-call gets
exactly one ``response`` event, including transport errors and cancellation.
"""


class LLMProviderError(RuntimeError):
    """Sanitized provider failure suitable for orchestration and UI mapping."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


@dataclass
class LLMMessage:
    role: str   # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: str = ""
    name: str = ""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    id: str = ""
    provider: str = ""
    finish_reason: str = ""
    native_finish_reason: str = ""
    finish_reasons: list[str] = field(default_factory=list)
    prompt_cached_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    reasoning_tokens: int = 0
    reported_total_tokens: int | None = None
    is_byok: bool | None = None
    cost: float | None = None
    cost_details: dict[str, Any] = field(default_factory=dict)
    latency: float | None = None
    wall_latency_seconds: float | None = None

    @property
    def total_tokens(self) -> int:
        """Provider-reported total when available, otherwise legacy total."""
        if self.reported_total_tokens is not None:
            return self.reported_total_tokens
        return self.prompt_tokens + self.completion_tokens

    @property
    def cached_tokens(self) -> int:
        """Alias for accounting consumers using OpenRouter's shorter name."""
        return self.prompt_cached_tokens


class LLMClient:
    """
    OpenRouter API client.
    Supports standard generation and tool-calling (for agent loops).
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        provider_routing: Mapping[str, Any] | None = None,
        reasoning_effort: str | None = None,
        request_observer: RequestObserver | None = None,
        transport: str = "openrouter",
        task_max_tokens: Mapping[str, int] | None = None,
        **sampler_kwargs: Any,
    ) -> None:
        self.api_key = api_key
        self.model = model
        # Round-trip through JSON both validates the config and ensures callers
        # cannot mutate an in-flight provider-routing payload.
        if transport not in _SUPPORTED_TRANSPORTS:
            raise ValueError("transport must be openrouter or deepseek_direct")
        if transport == "deepseek_direct" and provider_routing is not None:
            raise ValueError("direct DeepSeek requests cannot carry OpenRouter routing")
        self.transport = transport
        self.task_max_tokens: dict[str, int] = {}
        if task_max_tokens is not None:
            if not isinstance(task_max_tokens, Mapping):
                raise ValueError("task_max_tokens must be a mapping")
            for role, limit in task_max_tokens.items():
                if not isinstance(role, str) or not role:
                    raise ValueError("task_max_tokens roles must be non-empty strings")
                if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1_000_000:
                    raise ValueError("task_max_tokens values must be positive integers")
                self.task_max_tokens[role] = limit
        self.provider_routing = self._copy_optional_mapping(
            provider_routing, field_name="provider_routing"
        )
        if reasoning_effort is not None:
            if reasoning_effort not in {"low", "medium", "high"}:
                raise ValueError("reasoning_effort must be low, medium, or high")
        self.reasoning_effort = reasoning_effort
        self.request_observer = request_observer
        self.sampler = {
            "temperature": sampler_kwargs.get("temperature", 0.8),
            "top_p": sampler_kwargs.get("top_p", 0.95),
            "top_k": sampler_kwargs.get("top_k", 40),
            "max_tokens": sampler_kwargs.get("max_tokens", 1024),
        }

    @staticmethod
    def _copy_optional_mapping(
        value: Mapping[str, Any] | None, *, field_name: str
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError(f"{field_name} must be a mapping")
        try:
            copied = json.loads(json.dumps(dict(value)))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field_name} must be JSON-serializable") from error
        if not isinstance(copied, dict):  # Defensive: json decoding is dynamic.
            raise ValueError(f"{field_name} must encode to an object")
        return copied

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.transport == "openrouter":
            headers.update(
                {
                    "HTTP-Referer": "https://github.com/DilanRG/ai-murder-mystery",
                    "X-Title": "AI Murder Mystery Game",
                }
            )
        return headers

    def _messages_to_api(self, messages: list[LLMMessage]) -> list[dict]:
        """Convert internal message objects to OpenRouter API format."""
        result = []
        for msg in messages:
            d: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                d["tool_call_id"] = msg.tool_call_id
            if msg.name:
                d["name"] = msg.name
            result.append(d)
        return result

    async def generate(
        self,
        messages: list[LLMMessage],
        max_tokens: int | None = None,
        temperature: float | None = None,
        json_mode: bool = False,
        task_role: str = "unspecified",
    ) -> LLMResponse:
        """
        Basic generation — no tool calling.
        Use for story generation and NPC dialogue responses to the player.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages_to_api(messages),
            "max_tokens": self.task_max_tokens.get(
                task_role,
                self.sampler["max_tokens"] if max_tokens is None else max_tokens,
            ),
        }
        # Direct DeepSeek thinking mode documents these samplers as ignored, so
        # omit them rather than imply that they affect the measured comparison.
        if self.transport != "deepseek_direct" or self.reasoning_effort is None:
            # Zero is meaningful for schema-constrained planning; an ``or``
            # fallback would silently replace it with the prose temperature.
            payload["temperature"] = (
                self.sampler["temperature"] if temperature is None else temperature
            )
            payload["top_p"] = self.sampler["top_p"]
            if self.sampler.get("top_k"):
                payload["top_k"] = self.sampler["top_k"]
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        return await self._request(payload, task_role=task_role)

    async def generate_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        max_tokens: int | None = None,
        task_role: str = "tool_calling",
    ) -> LLMResponse:
        """
        Generation with tool-calling enabled — used exclusively for agent loops.
        Returns both text content and any tool calls the model wants to make.
        """
        if self.transport == "deepseek_direct" and self.reasoning_effort is not None:
            raise LLMProviderError(
                "Direct DeepSeek thinking mode does not support this tool-call interface.",
                code="provider_feature_unsupported",
                retryable=False,
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages_to_api(messages),
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": self.task_max_tokens.get(
                task_role, max_tokens or self.sampler["max_tokens"]
            ),
            "temperature": self.sampler["temperature"],
            "top_p": self.sampler["top_p"],
        }
        return await self._request(payload, task_role=task_role)

    def _apply_experiment_options(self, payload: dict[str, Any]) -> None:
        """Append transport-specific controls without changing legacy payloads."""
        if self.provider_routing is not None:
            # Copy once more because a mocked/observed request may mutate payload.
            payload["provider"] = json.loads(json.dumps(self.provider_routing))
        if self.transport == "deepseek_direct":
            # DeepSeek V4 defaults to thinking mode.  Send the toggle in both
            # directions so a no-reasoning repair/preflight cannot silently
            # spend its bounded output allowance on hidden reasoning tokens.
            payload["thinking"] = {
                "type": "enabled" if self.reasoning_effort is not None else "disabled"
            }
            if self.reasoning_effort is not None:
                payload["reasoning_effort"] = self.reasoning_effort
        elif self.reasoning_effort is not None:
            payload["reasoning"] = {"effort": self.reasoning_effort}

    async def _notify_observer(self, event: str, data: dict[str, Any]) -> None:
        if self.request_observer is None:
            return
        result = self.request_observer(event, data)
        if inspect.isawaitable(result):
            await result

    async def _request(
        self,
        payload: dict[str, Any],
        *,
        task_role: str,
    ) -> LLMResponse:
        """Run one observed request, settling an observer even on cancellation."""
        self._apply_experiment_options(payload)
        request_id = uuid.uuid4().hex
        # Observers receive only bounded accounting metadata. Prompt text,
        # character context, canonical truth, and private NPC state never cross
        # into the metrics/ledger boundary.
        prompt_tokens_upper_bound = max(
            1,
            len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
        )
        event_base = {
            "request_id": request_id,
            "started_at": datetime.now(UTC).isoformat(),
            "model": self.model,
            "task_role": task_role,
            "max_tokens": int(payload.get("max_tokens", 0)),
            "prompt_tokens_upper_bound": prompt_tokens_upper_bound,
            "provider_routing": self._copy_optional_mapping(
                self.provider_routing,
                field_name="provider_routing",
            ),
            "reasoning_effort": self.reasoning_effort,
            "transport": self.transport,
        }
        await self._notify_observer("pre_call", event_base)

        response: LLMResponse | None = None
        error: BaseException | None = None
        started = time.perf_counter()
        try:
            response = await self._post(payload)
            response.wall_latency_seconds = time.perf_counter() - started
            return response
        except BaseException as caught:
            error = caught
            raise
        finally:
            settlement = {
                **event_base,
                "response": response,
                "error": error,
                "cancelled": isinstance(error, asyncio.CancelledError),
            }
            # A cancelled caller must not strand a prior budget reservation.  The
            # shielded task gets a chance to settle before cancellation propagates.
            settle_task = asyncio.create_task(self._notify_observer("response", settlement))
            try:
                await asyncio.shield(settle_task)
            except asyncio.CancelledError:
                # Do not swallow repeated cancellation; wait for settlement then
                # re-raise so the caller still observes cancellation semantics.
                try:
                    await asyncio.shield(settle_task)
                finally:
                    raise

    async def _post(self, payload: dict[str, Any]) -> LLMResponse:
        """Send one OpenAI-compatible chat request and parse the response."""
        base_url = OPENROUTER_BASE_URL if self.transport == "openrouter" else DEEPSEEK_BASE_URL
        provider_label = "OpenRouter" if self.transport == "openrouter" else "DeepSeek"
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise self._sanitized_http_error(e) from e
            except httpx.TimeoutException as e:
                logger.error("%s request timed out", provider_label)
                raise LLMProviderError(
                    f"{provider_label} request timed out.",
                    code="provider_timeout",
                ) from e
            except httpx.RequestError as e:
                logger.error("%s request could not be completed", provider_label)
                raise LLMProviderError(
                    f"{provider_label} request could not be completed.",
                    code="provider_unavailable",
                ) from e

        data = resp.json()
        try:
            choice = data["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMProviderError(
                f"{provider_label} returned an invalid response.",
                code="provider_invalid_response",
                retryable=True,
            ) from error
        usage = data.get("usage", {})
        if not isinstance(usage, Mapping):
            usage = {}

        # Parse tool calls if present
        tool_calls: list[ToolCall] = []
        if raw_calls := msg.get("tool_calls"):
            for tc in raw_calls:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=args,
                ))

        return LLMResponse(
            content=msg.get("content") or "",
            tool_calls=tool_calls,
            prompt_tokens=self._int_value(usage.get("prompt_tokens")),
            completion_tokens=self._int_value(usage.get("completion_tokens")),
            model=(
                self._string_value(data.get("model"))
                or (self.model if self.transport == "openrouter" else "")
            ),
            id=self._string_value(data.get("id")),
            provider=self._string_value(data.get("provider")),
            finish_reason=self._string_value(choice.get("finish_reason")),
            native_finish_reason=self._string_value(choice.get("native_finish_reason")),
            finish_reasons=self._finish_reasons(data),
            prompt_cached_tokens=self._cached_prompt_tokens(usage),
            prompt_cache_miss_tokens=self._int_value(usage.get("prompt_cache_miss_tokens")),
            reasoning_tokens=self._reasoning_tokens(usage),
            reported_total_tokens=self._optional_int_value(usage.get("total_tokens")),
            # OpenRouter exposes accounting under ``usage`` for chat responses;
            # tolerate older top-level placement without treating an absent value
            # as a successful BYOK/cost verification.
            is_byok=self._optional_bool_value(usage.get("is_byok", data.get("is_byok"))),
            cost=self._optional_float_value(usage.get("cost", data.get("cost"))),
            cost_details=self._dict_value(usage.get("cost_details", data.get("cost_details"))),
            latency=self._optional_float_value(usage.get("latency", data.get("latency"))),
        )

    @staticmethod
    def _int_value(value: Any) -> int:
        parsed = LLMClient._optional_int_value(value)
        return parsed if parsed is not None else 0

    @staticmethod
    def _optional_int_value(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_float_value(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_bool_value(value: Any) -> bool | None:
        return value if isinstance(value, bool) else None

    @staticmethod
    def _string_value(value: Any) -> str:
        return value if isinstance(value, str) else ""

    @staticmethod
    def _dict_value(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    @classmethod
    def _cached_prompt_tokens(cls, usage: Mapping[str, Any]) -> int:
        details = cls._dict_value(usage.get("prompt_tokens_details"))
        return cls._int_value(
            usage.get(
                "prompt_cache_hit_tokens",
                details.get("cached_tokens", details.get("cache_read_input_tokens")),
            )
        )

    @classmethod
    def _reasoning_tokens(cls, usage: Mapping[str, Any]) -> int:
        details = cls._dict_value(usage.get("completion_tokens_details"))
        return cls._int_value(details.get("reasoning_tokens"))

    @classmethod
    def _finish_reasons(cls, data: Mapping[str, Any]) -> list[str]:
        choices = data.get("choices")
        if not isinstance(choices, list):
            return []
        reasons = []
        for item in choices:
            if isinstance(item, Mapping) and isinstance(item.get("finish_reason"), str):
                reasons.append(item["finish_reason"])
        return reasons

    def _sanitized_http_error(self, error: httpx.HTTPStatusError) -> LLMProviderError:
        status_code = error.response.status_code
        if status_code in {401, 403}:
            code, retryable = "provider_auth_failed", False
        elif status_code == 429:
            code, retryable = "provider_rate_limited", True
        elif status_code >= 500:
            code, retryable = "provider_unavailable", True
        else:
            code, retryable = "provider_rejected_request", False
        provider_label = "OpenRouter" if self.transport == "openrouter" else "DeepSeek"
        logger.error("%s request failed with status %s (%s)", provider_label, status_code, code)
        return LLMProviderError(
            f"{provider_label} request failed.",
            code=code,
            status_code=status_code,
            retryable=retryable,
        )

    async def query_generation_stats(self, generation_id: str) -> dict[str, Any]:
        """Fetch authenticated OpenRouter generation accounting by safe ID only."""
        if not isinstance(generation_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", generation_id):
            raise ValueError("generation_id must be a non-empty safe identifier")
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                response = await client.get(
                    f"{OPENROUTER_BASE_URL}/generation",
                    headers=self._headers(),
                    params={"id": generation_id},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise self._sanitized_http_error(error) from error
            except httpx.TimeoutException as error:
                logger.error("OpenRouter generation stats request timed out")
                raise LLMProviderError(
                    "OpenRouter generation stats request timed out.", code="provider_timeout"
                ) from error
            except httpx.RequestError as error:
                logger.error("OpenRouter generation stats request could not be completed")
                raise LLMProviderError(
                    "OpenRouter generation stats request could not be completed.",
                    code="provider_unavailable",
                ) from error
        body = response.json()
        if not isinstance(body, dict):
            raise LLMProviderError(
                "OpenRouter returned invalid generation stats.",
                code="provider_invalid_response",
                retryable=True,
            )
        raw = body.get("data", body)
        if not isinstance(raw, Mapping):
            raise LLMProviderError(
                "OpenRouter returned invalid generation stats.",
                code="provider_invalid_response",
                retryable=True,
            )
        provider_responses = []
        raw_provider_responses = raw.get("provider_responses")
        if isinstance(raw_provider_responses, list):
            for item in raw_provider_responses[:16]:
                if not isinstance(item, Mapping):
                    continue
                provider_responses.append(
                    {
                        "provider_name": self._string_value(
                            item.get("provider_name", item.get("provider"))
                        ),
                        "status_code": self._optional_int_value(
                            item.get("status_code", item.get("status"))
                        ),
                    }
                )
        # Strict allowlist: the metadata endpoint can contain referers, user
        # identifiers, or stored content that must never enter experiment logs.
        return {
            "id": self._string_value(raw.get("id")),
            "model": self._string_value(raw.get("model")),
            "provider_name": self._string_value(raw.get("provider_name")),
            "is_byok": self._optional_bool_value(raw.get("is_byok")),
            "finish_reason": self._string_value(raw.get("finish_reason")),
            "native_finish_reason": self._string_value(raw.get("native_finish_reason")),
            "native_tokens_prompt": self._optional_int_value(raw.get("native_tokens_prompt")),
            "native_tokens_cached": self._optional_int_value(raw.get("native_tokens_cached")),
            "native_tokens_completion": self._optional_int_value(raw.get("native_tokens_completion")),
            "native_tokens_reasoning": self._optional_int_value(raw.get("native_tokens_reasoning")),
            "latency_ms": self._optional_float_value(raw.get("latency")),
            "generation_time_ms": self._optional_float_value(raw.get("generation_time")),
            "total_cost": self._optional_float_value(raw.get("total_cost")),
            "upstream_inference_cost": self._optional_float_value(
                raw.get("upstream_inference_cost")
            ),
            "provider_responses": provider_responses,
        }

    async def fetch_current_key_usage(self) -> dict[str, Any]:
        """Return a label-free usage baseline for the authenticated key."""

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                response = await client.get(
                    f"{OPENROUTER_BASE_URL}/key",
                    headers=self._headers(),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise self._sanitized_http_error(error) from error
            except httpx.TimeoutException as error:
                raise LLMProviderError(
                    "OpenRouter key usage request timed out.",
                    code="provider_timeout",
                ) from error
            except httpx.RequestError as error:
                raise LLMProviderError(
                    "OpenRouter key usage request could not be completed.",
                    code="provider_unavailable",
                ) from error
        body = response.json()
        raw = body.get("data") if isinstance(body, Mapping) else None
        if not isinstance(raw, Mapping):
            raise LLMProviderError(
                "OpenRouter returned invalid key usage metadata.",
                code="provider_invalid_response",
                retryable=True,
            )
        numeric_fields = (
            "byok_usage",
            "byok_usage_daily",
            "byok_usage_weekly",
            "byok_usage_monthly",
            "usage",
            "usage_daily",
            "usage_weekly",
            "usage_monthly",
            "limit",
            "limit_remaining",
        )
        return {
            field: self._optional_float_value(raw.get(field))
            for field in numeric_fields
        } | {"include_byok_in_limit": self._optional_bool_value(raw.get("include_byok_in_limit"))}

    async def fetch_current_balance(self) -> dict[str, Any]:
        """Return sanitized direct-DeepSeek balance data for experiment baselines."""

        if self.transport != "deepseek_direct":
            raise ValueError("balance lookup is available only for direct DeepSeek")
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                response = await client.get(
                    f"{DEEPSEEK_BASE_URL}/user/balance",
                    headers=self._headers(),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise self._sanitized_http_error(error) from error
            except httpx.TimeoutException as error:
                raise LLMProviderError(
                    "DeepSeek balance request timed out.", code="provider_timeout"
                ) from error
            except httpx.RequestError as error:
                raise LLMProviderError(
                    "DeepSeek balance request could not be completed.",
                    code="provider_unavailable",
                ) from error
        body = response.json()
        if not isinstance(body, Mapping) or not isinstance(body.get("balance_infos"), list):
            raise LLMProviderError(
                "DeepSeek returned invalid balance data.",
                code="provider_invalid_response",
                retryable=True,
            )
        balances: list[dict[str, str]] = []
        for item in body["balance_infos"]:
            if not isinstance(item, Mapping):
                continue
            currency = self._string_value(item.get("currency"))
            total = self._string_value(item.get("total_balance"))
            if currency in {"USD", "CNY"} and total:
                balances.append({"currency": currency, "total_balance": total})
        return {
            "is_available": body.get("is_available") is True,
            "balances": balances,
        }

    @staticmethod
    async def fetch_models(api_key: str) -> list[dict[str, Any]]:
        """
        Fetch the list of available models from OpenRouter.
        Returns a list of model dicts with id, name, pricing, context_length.
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{OPENROUTER_BASE_URL}/models", headers=headers)
            resp.raise_for_status()

        models = resp.json().get("data", [])
        results = []
        for m in models:
            pricing = m.get("pricing", {})
            prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
            completion_price = float(pricing.get("completion", "0")) * 1_000_000
            is_free = prompt_price == 0 and completion_price == 0
            results.append({
                "id": m.get("id", ""),
                "name": m.get("name", m.get("id", "")),
                "context_length": m.get("context_length", 0),
                "prompt_price_per_1m": round(prompt_price, 4),
                "completion_price_per_1m": round(completion_price, 4),
                "is_free": is_free,
                "provider": m.get("id", "").split("/")[0] if "/" in m.get("id", "") else "",
            })
        results.sort(key=lambda x: (not x["is_free"], x["name"].lower()))
        return results
