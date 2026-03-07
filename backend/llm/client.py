"""
OpenRouter LLM client with tool-calling support.
Handles all LLM interactions for both story generation and agent loops.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from config.settings import OPENROUTER_BASE_URL

logger = logging.getLogger(__name__)


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

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient:
    """
    OpenRouter API client.
    Supports standard generation and tool-calling (for agent loops).
    """

    def __init__(self, api_key: str, model: str, **sampler_kwargs: Any) -> None:
        self.api_key = api_key
        self.model = model
        self.sampler = {
            "temperature": sampler_kwargs.get("temperature", 0.8),
            "top_p": sampler_kwargs.get("top_p", 0.95),
            "top_k": sampler_kwargs.get("top_k", 40),
            "max_tokens": sampler_kwargs.get("max_tokens", 1024),
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/DilanRG/ai-murder-mystery",
            "X-Title": "AI Murder Mystery",
        }

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
    ) -> LLMResponse:
        """
        Basic generation — no tool calling.
        Use for story generation and NPC dialogue responses to the player.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages_to_api(messages),
            "max_tokens": max_tokens or self.sampler["max_tokens"],
            "temperature": temperature or self.sampler["temperature"],
            "top_p": self.sampler["top_p"],
        }
        if self.sampler.get("top_k"):
            payload["top_k"] = self.sampler["top_k"]
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        return await self._post(payload)

    async def generate_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """
        Generation with tool-calling enabled — used exclusively for agent loops.
        Returns both text content and any tool calls the model wants to make.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages_to_api(messages),
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": max_tokens or self.sampler["max_tokens"],
            "temperature": self.sampler["temperature"],
            "top_p": self.sampler["top_p"],
        }
        return await self._post(payload)

    async def _post(self, payload: dict[str, Any]) -> LLMResponse:
        """Send a request to OpenRouter and parse the response."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                resp = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = e.response.text
                logger.error("LLM API error %s: %s", e.response.status_code, body)
                raise RuntimeError(f"LLM API error {e.response.status_code}: {body}") from e
            except httpx.RequestError as e:
                logger.error("LLM request failed: %s", e)
                raise RuntimeError(f"LLM request failed: {e}") from e

        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        usage = data.get("usage", {})

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
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", self.model),
        )

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
