"""Small transport-unit tests for optional provider configuration."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from llm.client import LLMClient, LLMMessage, LLMProviderError, LLMResponse


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


def test_experiment_options_add_exact_openrouter_payload_without_affecting_legacy() -> None:
    client = LLMClient(
        api_key="test",
        model="deepseek/deepseek-v4",
        provider_routing={"order": ["deepseek"], "allow_fallbacks": False},
        reasoning_effort="high",
    )
    captured: dict[str, object] = {}

    async def fake_post(payload: dict[str, object]) -> LLMResponse:
        captured.update(payload)
        return LLMResponse(content="{}")

    client._post = fake_post  # type: ignore[method-assign]
    asyncio.run(client.generate([LLMMessage(role="user", content="plan")]))

    assert captured["provider"] == {"order": ["deepseek"], "allow_fallbacks": False}
    assert captured["reasoning"] == {"effort": "high"}

    legacy = LLMClient(api_key="test", model="deepseek/deepseek-v4")
    legacy_payload: dict[str, object] = {}

    async def fake_legacy_post(payload: dict[str, object]) -> LLMResponse:
        legacy_payload.update(payload)
        return LLMResponse(content="{}")

    legacy._post = fake_legacy_post  # type: ignore[method-assign]
    asyncio.run(legacy.generate([LLMMessage(role="user", content="plan")]))
    assert "provider" not in legacy_payload
    assert "reasoning" not in legacy_payload


def test_explicit_none_omits_top_k_without_changing_legacy_default() -> None:
    client = LLMClient(api_key="test", model="test/model", top_k=None)
    captured: dict[str, object] = {}

    async def fake_post(payload: dict[str, object]) -> LLMResponse:
        captured.update(payload)
        return LLMResponse(content="{}")

    client._post = fake_post  # type: ignore[method-assign]
    asyncio.run(client.generate([LLMMessage(role="user", content="plan")]))

    assert "top_k" not in captured
    assert LLMClient(api_key="test", model="test/model").sampler["top_k"] == 40


def test_direct_deepseek_uses_exact_endpoint_headers_and_thinking_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["referer"] = request.headers.get("http-referer")
        captured["payload"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "direct-1",
                "model": "deepseek-v4-flash",
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 2,
                },
                "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}],
            },
        )

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    class MockClient(original_async_client):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(transport=transport, **kwargs)

    monkeypatch.setattr("llm.client.httpx.AsyncClient", MockClient)
    client = LLMClient(
        api_key="direct-secret",
        model="deepseek-v4-flash",
        transport="deepseek_direct",
        reasoning_effort="high",
        top_k=None,
    )
    response = asyncio.run(client.generate([LLMMessage(role="user", content="OK")]))

    payload = captured["payload"]
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["authorization"] == "Bearer direct-secret"
    assert captured["referer"] is None
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"
    assert "provider" not in payload
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert response.provider == ""
    assert response.prompt_cache_miss_tokens == 2


def test_direct_deepseek_explicitly_disables_default_thinking_mode() -> None:
    captured: dict[str, object] = {}
    client = LLMClient(
        api_key="test",
        model="deepseek-v4-flash",
        transport="deepseek_direct",
        reasoning_effort=None,
    )

    async def fake_post(payload: dict[str, object]) -> LLMResponse:
        captured.update(payload)
        return LLMResponse(content="OK", model="deepseek-v4-flash")

    client._post = fake_post  # type: ignore[method-assign]
    asyncio.run(client.generate([LLMMessage(role="user", content="OK")]))

    assert captured["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in captured
    assert captured["temperature"] == 0.8
    assert captured["top_p"] == 0.95


def test_direct_transport_rejects_openrouter_routing() -> None:
    with pytest.raises(ValueError, match="cannot carry OpenRouter routing"):
        LLMClient(
            api_key="test",
            model="deepseek-v4-pro",
            transport="deepseek_direct",
            provider_routing={"only": ["deepseek"]},
        )


def test_direct_thinking_mode_rejects_tool_calls_before_transport() -> None:
    client = LLMClient(
        api_key="test",
        model="deepseek-v4-pro",
        transport="deepseek_direct",
        reasoning_effort="high",
    )
    with pytest.raises(LLMProviderError) as caught:
        asyncio.run(
            client.generate_with_tools(
                [LLMMessage(role="user", content="use a tool")],
                [{"type": "function", "function": {"name": "noop"}}],
            )
        )
    assert caught.value.code == "provider_feature_unsupported"
    assert caught.value.retryable is False


def test_measured_task_limit_overrides_a_lower_production_adapter_limit() -> None:
    captured: dict[str, object] = {}
    client = LLMClient(
        api_key="test",
        model="deepseek-v4-flash",
        transport="deepseek_direct",
        reasoning_effort="high",
        task_max_tokens={"case_generation": 32_768},
    )

    async def fake_post(payload: dict[str, object]) -> LLMResponse:
        captured.update(payload)
        return LLMResponse(content="{}")

    client._post = fake_post  # type: ignore[method-assign]
    asyncio.run(
        client.generate(
            [LLMMessage(role="user", content="json")],
            max_tokens=16_384,
            task_role="case_generation",
        )
    )
    assert captured["max_tokens"] == 32_768


def test_direct_response_does_not_synthesize_missing_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "id": "direct-missing-model",
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 1,
                },
                "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}],
            },
        )
    )
    original_async_client = httpx.AsyncClient

    class MockClient(original_async_client):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(transport=transport, **kwargs)

    monkeypatch.setattr("llm.client.httpx.AsyncClient", MockClient)
    client = LLMClient(
        api_key="test",
        model="deepseek-v4-pro",
        transport="deepseek_direct",
    )
    response = asyncio.run(client.generate([LLMMessage(role="user", content="OK")]))
    assert response.model == ""


def test_direct_balance_baseline_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    response_body = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "USD",
                "total_balance": "1.00",
                "granted_balance": "private-detail",
                "topped_up_balance": "private-detail",
            }
        ],
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response_body))
    original_async_client = httpx.AsyncClient

    class MockClient(original_async_client):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(transport=transport, **kwargs)

    monkeypatch.setattr("llm.client.httpx.AsyncClient", MockClient)
    client = LLMClient(
        api_key="direct-secret",
        model="deepseek-v4-flash",
        transport="deepseek_direct",
    )
    baseline = asyncio.run(client.fetch_current_balance())

    assert baseline == {
        "is_available": True,
        "balances": [{"currency": "USD", "total_balance": "1.00"}],
    }
    assert "private-detail" not in repr(baseline)


def test_response_parses_provider_accounting_and_finish_details(monkeypatch: pytest.MonkeyPatch) -> None:
    response_body = {
        "id": "gen-123",
        "model": "deepseek/deepseek-v4",
        "provider": "DeepSeek",
        "latency": 1.75,
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "total_tokens": 200,
            "prompt_tokens_details": {"cached_tokens": 25},
            "completion_tokens_details": {"reasoning_tokens": 40},
            "is_byok": False,
            "cost": "0.0125",
            "cost_details": {"upstream_inference_cost": 0.01},
        },
        "choices": [
            {
                "finish_reason": "stop",
                "native_finish_reason": "eos",
                "message": {"content": "accepted"},
            },
            {"finish_reason": "length", "message": {"content": "ignored"}},
        ],
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response_body))

    original_async_client = httpx.AsyncClient

    class MockClient(original_async_client):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(transport=transport, **kwargs)

    monkeypatch.setattr("llm.client.httpx.AsyncClient", MockClient)
    client = LLMClient(api_key="secret-key", model="fallback/model")
    response = asyncio.run(client.generate([LLMMessage(role="user", content="hello")]))

    assert response.id == "gen-123"
    assert response.model == "deepseek/deepseek-v4"
    assert response.provider == "DeepSeek"
    assert response.finish_reason == "stop"
    assert response.native_finish_reason == "eos"
    assert response.finish_reasons == ["stop", "length"]
    assert response.prompt_tokens == 120
    assert response.prompt_cached_tokens == response.cached_tokens == 25
    assert response.completion_tokens == 80
    assert response.reasoning_tokens == 40
    assert response.total_tokens == 200
    assert response.is_byok is False
    assert response.cost == 0.0125
    assert response.cost_details == {"upstream_inference_cost": 0.01}
    assert response.latency == 1.75


def test_generation_stats_query_is_authenticated_and_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "gen-123",
                    "model": "deepseek/deepseek-v4-pro",
                    "provider_name": "DeepSeek",
                    "is_byok": True,
                    "total_cost": 0.002,
                    "upstream_inference_cost": 0.02,
                    "external_user": "must-not-survive",
                }
            },
        )

    transport = httpx.MockTransport(handler)

    original_async_client = httpx.AsyncClient

    class MockClient(original_async_client):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(transport=transport, **kwargs)

    monkeypatch.setattr("llm.client.httpx.AsyncClient", MockClient)
    client = LLMClient(api_key="secret-key", model="test/model")
    stats = asyncio.run(client.query_generation_stats("gen-123"))
    assert stats["id"] == "gen-123"
    assert stats["model"] == "deepseek/deepseek-v4-pro"
    assert stats["provider_name"] == "DeepSeek"
    assert stats["is_byok"] is True
    assert stats["total_cost"] == 0.002
    assert stats["upstream_inference_cost"] == 0.02
    assert "external_user" not in stats
    assert captured["url"] == "https://openrouter.ai/api/v1/generation?id=gen-123"
    assert captured["authorization"] == "Bearer secret-key"

    with pytest.raises(ValueError, match="safe identifier"):
        asyncio.run(client.query_generation_stats("gen-123&api_key=secret-key"))

    def rejected(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="secret-key must never surface")

    rejected_transport = httpx.MockTransport(rejected)

    class RejectedClient(original_async_client):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(transport=rejected_transport, **kwargs)

    monkeypatch.setattr("llm.client.httpx.AsyncClient", RejectedClient)
    with pytest.raises(LLMProviderError) as error:
        asyncio.run(client.query_generation_stats("gen-123"))
    assert error.value.code == "provider_auth_failed"
    assert "secret-key" not in str(error.value)


def test_key_usage_baseline_excludes_key_label(monkeypatch: pytest.MonkeyPatch) -> None:
    response_body = {
        "data": {
            "label": "private-key-label-example",
            "creator_user_id": "private-user",
            "byok_usage": 1.25,
            "byok_usage_monthly": 1.0,
            "usage": 2.5,
            "limit": 10,
            "limit_remaining": 7.5,
            "include_byok_in_limit": True,
        }
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response_body))
    original_async_client = httpx.AsyncClient

    class MockClient(original_async_client):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(transport=transport, **kwargs)

    monkeypatch.setattr("llm.client.httpx.AsyncClient", MockClient)
    client = LLMClient(api_key="secret-key", model="test/model")
    baseline = asyncio.run(client.fetch_current_key_usage())

    assert baseline["byok_usage"] == 1.25
    assert baseline["limit_remaining"] == 7.5
    assert baseline["include_byok_in_limit"] is True
    assert "label" not in baseline
    assert "private-user" not in repr(baseline)


def test_observer_settles_after_response_and_cancellation() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    async def observer(event: str, data: dict[str, object]) -> None:
        events.append((event, data))

    client = LLMClient(api_key="secret-key", model="test/model", request_observer=observer)

    async def fake_post(_: dict[str, object]) -> LLMResponse:
        return LLMResponse(content="ok")

    client._post = fake_post  # type: ignore[method-assign]
    asyncio.run(client.generate([LLMMessage(role="user", content="hello")]))
    assert [event for event, _ in events] == ["pre_call", "response"]
    assert events[0][1]["request_id"] == events[1][1]["request_id"]
    assert "secret-key" not in repr(events)
    assert "payload" not in events[0][1]
    assert events[0][1]["task_role"] == "unspecified"
    assert events[0][1]["started_at"].endswith("+00:00")
    assert events[0][1]["prompt_tokens_upper_bound"] > 0

    async def cancelled_post(_: dict[str, object]) -> LLMResponse:
        raise asyncio.CancelledError()

    client._post = cancelled_post  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.generate([LLMMessage(role="user", content="hello")]))
    assert [event for event, _ in events] == ["pre_call", "response", "pre_call", "response"]
    assert events[-1][1]["cancelled"] is True
