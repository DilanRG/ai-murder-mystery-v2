"""Tests for the non-authoritative dialogue portrayal boundary."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from game.portrayal import (
    MAX_PROVIDER_UTTERANCE_CHARS,
    ConstrainedPortrayalCoordinator,
    OpenRouterPortrayalAdapter,
    PermittedFact,
    PortrayalRequest,
    PortrayalSource,
)


def _request() -> PortrayalRequest:
    return PortrayalRequest(
        character_id="edgar_blackwood",
        character_name="Edgar Blackwood",
        speaking_style="measured, exacting, and defensive under pressure",
        emotional_state="controlled unease",
        player_question="Where were you when the lights failed?",
        canonical_claim="I was in the library shortly before the blackout.",
        permitted_facts=(
            PermittedFact(
                id="fact_edgar_library",
                statement="Edgar says he was in the library before the blackout.",
            ),
        ),
    )


class _StaticProvider:
    def __init__(self, output: object) -> None:
        self.output = output

    async def portray(self, request: PortrayalRequest) -> object:
        return self.output


class _FailingProvider:
    async def portray(self, request: PortrayalRequest) -> str:
        raise RuntimeError("provider unavailable")


class _SlowProvider:
    async def portray(self, request: PortrayalRequest) -> str:
        await asyncio.sleep(0.1)
        return '{"utterance":"too late","referenced_fact_ids":[]}'


def test_valid_provider_portrayal_keeps_authoritative_claim_separate() -> None:
    request = _request()
    result = asyncio.run(
        ConstrainedPortrayalCoordinator(
            _StaticProvider(
                '{"utterance":"I was in the library, as I already said.",'
                '"referenced_fact_ids":["fact_edgar_library"]}'
            )
        ).portray(request)
    )

    assert result.source is PortrayalSource.PROVIDER
    assert result.canonical_claim == request.canonical_claim
    assert result.surface_utterance == "I was in the library, as I already said."
    assert result.referenced_fact_ids == ("fact_edgar_library",)


def test_hallucinated_fact_reference_falls_back_without_leaking_truth() -> None:
    request = _request()
    result = asyncio.run(
        ConstrainedPortrayalCoordinator(
            _StaticProvider(
                {"utterance": "The secret ledger proves it.", "referenced_fact_ids": ["secret_ledger"]}
            )
        ).portray(request)
    )

    assert result.source is PortrayalSource.FALLBACK
    assert result.surface_utterance == request.canonical_claim
    assert result.referenced_fact_ids == ()


def test_malformed_oversized_and_action_outputs_each_fall_back() -> None:
    request = _request()
    unsafe_outputs = (
        "not a JSON document",
        {"utterance": "x" * (MAX_PROVIDER_UTTERANCE_CHARS + 1), "referenced_fact_ids": []},
        {
            "utterance": "I will move to the study.",
            "referenced_fact_ids": [],
            "action": {"kind": "move", "room_id": "study"},
        },
    )

    for output in unsafe_outputs:
        result = asyncio.run(
            ConstrainedPortrayalCoordinator(_StaticProvider(output)).portray(request)
        )
        assert result.source is PortrayalSource.FALLBACK
        assert result.canonical_claim == request.canonical_claim


def test_provider_failure_timeout_and_no_provider_use_deterministic_fallback() -> None:
    request = _request()
    coordinators = (
        ConstrainedPortrayalCoordinator(_FailingProvider()),
        ConstrainedPortrayalCoordinator(_SlowProvider(), timeout_seconds=0.001),
        ConstrainedPortrayalCoordinator(),
    )

    for coordinator in coordinators:
        result = asyncio.run(coordinator.portray(request))
        assert result.source is PortrayalSource.FALLBACK
        assert result.surface_utterance == request.canonical_claim


def test_request_rejects_secret_or_world_fields() -> None:
    payload = _request().model_dump()
    payload["murderer_id"] = "edgar_blackwood"

    try:
        PortrayalRequest.model_validate(payload)
    except ValueError as exc:
        assert "murderer_id" in str(exc)
    else:  # pragma: no cover - documents the security boundary
        raise AssertionError("secret fields must not cross the portrayal boundary")


def test_openrouter_adapter_uses_only_safe_generated_messages() -> None:
    class FakeClient:
        async def generate(self, messages, **kwargs):
            self.messages = messages
            self.kwargs = kwargs
            return SimpleNamespace(
                content='{"utterance":"The library, briefly.","referenced_fact_ids":[]}'
            )

    client = FakeClient()
    raw = asyncio.run(OpenRouterPortrayalAdapter(client).portray(_request()))

    assert '"utterance"' in raw
    assert client.kwargs == {"max_tokens": 220, "temperature": 0.2, "json_mode": True}
    sent_text = "\n".join(message.content for message in client.messages)
    assert "character-card" not in sent_text
    assert "murderer_id" not in sent_text
    assert "generate_with_tools" not in sent_text
