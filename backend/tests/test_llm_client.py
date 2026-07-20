"""Small transport-unit tests for optional provider configuration."""

from __future__ import annotations

import asyncio

from llm.client import LLMClient, LLMMessage, LLMResponse


def test_generate_preserves_explicit_zero_temperature() -> None:
    client = LLMClient(api_key="test", model="test/model", temperature=0.8, max_tokens=900)
    captured: dict[str, object] = {}

    async def fake_post(payload: dict[str, object]) -> LLMResponse:
        captured.update(payload)
        return LLMResponse(content="{}")

    client._post = fake_post  # type: ignore[method-assign]
    asyncio.run(
        client.generate(
            [LLMMessage(role="user", content="choose")],
            temperature=0.0,
            max_tokens=1,
            json_mode=True,
        )
    )

    assert captured["temperature"] == 0.0
    assert captured["max_tokens"] == 1
    assert captured["response_format"] == {"type": "json_object"}
