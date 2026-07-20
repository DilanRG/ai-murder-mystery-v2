"""Adversarial tests for the constrained NPC intent planning boundary."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from game.npc_planning import (
    MAX_NPC_ACTORS,
    MAX_PROVIDER_JSON_BYTES,
    ConstrainedNpcIntentPlanningCoordinator,
    NpcActionCandidate,
    NpcActorActionOptions,
    NpcIntentPlanningRequest,
    NpcPlanningSource,
    OpenRouterNpcIntentBatchAdapter,
    SafeNpcTurnSnapshot,
)


def _request() -> NpcIntentPlanningRequest:
    return NpcIntentPlanningRequest(
        snapshot=SafeNpcTurnSnapshot(
            turn_number=4,
            phase="investigation",
            public_scene_summary="A storm has trapped everyone in Ashwick Manor.",
            public_event_summaries=("The lights failed briefly.",),
        ),
        actor_options=(
            NpcActorActionOptions(
                actor_id="edgar",
                candidates=(
                    NpcActionCandidate(action_id="move_library", summary="Go to the library."),
                    NpcActionCandidate(action_id="wait_hall", summary="Wait in the hall."),
                ),
            ),
            NpcActorActionOptions(
                actor_id="elena",
                candidates=(
                    NpcActionCandidate(action_id="check_study", summary="Check the study."),
                    NpcActionCandidate(action_id="wait_hall", summary="Wait in the hall."),
                ),
            ),
        ),
    )


class _StaticProvider:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls = 0

    async def plan_intents(self, request: NpcIntentPlanningRequest) -> object:
        self.calls += 1
        return self.output


class _SlowProvider:
    async def plan_intents(self, request: NpcIntentPlanningRequest) -> str:
        await asyncio.sleep(0.1)
        return '{"selections":[]}'


def test_valid_batch_selects_exactly_one_candidate_per_actor_once() -> None:
    provider = _StaticProvider(
        {"selections": [
            {"actor_id": "edgar", "action_id": "wait_hall"},
            {"actor_id": "elena", "action_id": "check_study"},
        ]}
    )
    result = asyncio.run(ConstrainedNpcIntentPlanningCoordinator(provider).plan(_request()))

    assert provider.calls == 1
    assert result.source is NpcPlanningSource.PROVIDER
    assert [(choice.actor_id, choice.action_id) for choice in result.selections] == [
        ("edgar", "wait_hall"), ("elena", "check_study")
    ]


@pytest.mark.parametrize(
    "output",
    (
        "not json",
        {"selections": [{"actor_id": "edgar", "action_id": "move_library"}]},
        {"selections": [
            {"actor_id": "edgar", "action_id": "move_library"},
            {"actor_id": "edgar", "action_id": "wait_hall"},
        ]},
        {"selections": [
            {"actor_id": "edgar", "action_id": "teleport_world"},
            {"actor_id": "elena", "action_id": "check_study"},
        ]},
        {"selections": [
            {"actor_id": "edgar", "action_id": "move_library"},
            {"actor_id": "elena", "action_id": "check_study"},
        ], "state_patch": {"murderer": "edgar"}},
        "x" * (MAX_PROVIDER_JSON_BYTES + 1),
    ),
)
def test_malformed_minus_and_unsafe_provider_outputs_fall_back(output: object) -> None:
    result = asyncio.run(ConstrainedNpcIntentPlanningCoordinator(_StaticProvider(output)).plan(_request()))

    assert result.source is NpcPlanningSource.FALLBACK
    assert [(choice.actor_id, choice.action_id) for choice in result.selections] == [
        ("edgar", "move_library"), ("elena", "check_study")
    ]


def test_no_provider_and_timeout_fall_back_deterministically() -> None:
    request = _request()
    for coordinator in (
        ConstrainedNpcIntentPlanningCoordinator(),
        ConstrainedNpcIntentPlanningCoordinator(_SlowProvider(), timeout_seconds=0.001),
    ):
        result = asyncio.run(coordinator.plan(request))
        assert result.source is NpcPlanningSource.FALLBACK
        assert len(result.selections) == len(request.actor_options)


def test_million_and_minus_input_bounds_are_rejected_before_a_provider_call() -> None:
    payload = _request().model_dump()
    payload["snapshot"]["turn_number"] = -1
    with pytest.raises(ValueError):
        NpcIntentPlanningRequest.model_validate(payload)

    payload = _request().model_dump()
    payload["actor_options"] = payload["actor_options"] * (MAX_NPC_ACTORS + 1)
    with pytest.raises(ValueError):
        NpcIntentPlanningRequest.model_validate(payload)


def test_request_is_frozen_and_rejects_hidden_or_patch_fields() -> None:
    request = _request()
    with pytest.raises(Exception):
        request.snapshot.phase = "ended"

    payload = request.model_dump()
    payload["state_patch"] = {"turn_number": 999}
    with pytest.raises(ValueError):
        NpcIntentPlanningRequest.model_validate(payload)


def test_openrouter_adapter_sends_only_the_safe_request_and_requests_json() -> None:
    class FakeClient:
        async def generate(self, messages, **kwargs):
            self.messages = messages
            self.kwargs = kwargs
            return SimpleNamespace(content='{"selections":[]}')

    client = FakeClient()
    raw = asyncio.run(OpenRouterNpcIntentBatchAdapter(client).plan_intents(_request()))

    assert raw == '{"selections":[]}'
    assert client.kwargs == {"max_tokens": 320, "temperature": 0.0, "json_mode": True}
    sent_text = "\n".join(message.content for message in client.messages)
    assert "murderer_id" not in sent_text
    assert "state_patch" not in sent_text
    assert "character-card" not in sent_text
