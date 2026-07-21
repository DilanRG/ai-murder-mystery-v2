"""Adversarial tests for isolated private NPC agent action selection."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from game.npc_planning import NpcActionCandidate, NpcActorActionOptions, SafeNpcTurnSnapshot
from game.private_npc_agents import (
    MAX_PRIVATE_NPC_AGENTS,
    OpenRouterPrivateNpcAgentAdapter,
    PrivateNpcAgentCoordinator,
    PrivateNpcAgentFailureReason,
    PrivateNpcAgentRequest,
    PrivateNpcAgentSource,
    PrivateNpcBriefing,
    PrivateNpcFact,
    PrivateNpcRuntimeState,
)


def _request(actor_id: str) -> PrivateNpcAgentRequest:
    return PrivateNpcAgentRequest(
        actor_id=actor_id,
        private_briefing=PrivateNpcBriefing(
            character_summary=f"{actor_id} has a private motive.",
            private_facts=(PrivateNpcFact(id=f"{actor_id}-fact", statement="Keep this private."),),
        ),
        runtime_state=PrivateNpcRuntimeState(state_summary="Alert.", urgency=2),
        snapshot=SafeNpcTurnSnapshot(
            turn_number=4, phase="investigation", public_scene_summary="Stormy manor."
        ),
        actor_options=NpcActorActionOptions(
            actor_id=actor_id,
            candidates=(
                NpcActionCandidate(action_id=f"{actor_id}-first", summary="Wait."),
                NpcActionCandidate(action_id=f"{actor_id}-second", summary="Move."),
            ),
        ),
    )


def test_seven_isolated_requests_are_concurrent_and_valid() -> None:
    class Provider:
        def __init__(self) -> None:
            self.requests: list[PrivateNpcAgentRequest] = []

        async def plan_action(self, request):
            self.requests.append(request)
            await asyncio.sleep(0)
            return {"action_id": request.actor_options.candidates[1].action_id}

    provider = Provider()
    requests = tuple(_request(f"actor-{number}") for number in range(MAX_PRIVATE_NPC_AGENTS))
    plan = asyncio.run(PrivateNpcAgentCoordinator(provider).plan_all(requests))

    assert len(provider.requests) == MAX_PRIVATE_NPC_AGENTS
    assert set(plan.selections) == {request.actor_id for request in requests}
    assert all(source is PrivateNpcAgentSource.PROVIDER for source in plan.sources.values())
    assert all(selection.action_id.endswith("-second") for selection in plan.selections.values())


def test_malformed_response_falls_back_for_only_that_actor() -> None:
    class Provider:
        async def plan_action(self, request):
            if request.actor_id == "bad":
                return {"action_id": request.actor_options.candidates[1].action_id, "state_patch": {}}
            return {"action_id": request.actor_options.candidates[1].action_id}

    plan = asyncio.run(PrivateNpcAgentCoordinator(Provider()).plan_all((_request("good"), _request("bad"))))
    assert plan.selections["good"].action_id == "good-second"
    assert plan.sources["good"] is PrivateNpcAgentSource.PROVIDER
    assert plan.selections["bad"].action_id == "bad-first"
    assert plan.sources["bad"] is PrivateNpcAgentSource.FALLBACK
    assert plan.failure_reasons == {
        "bad": PrivateNpcAgentFailureReason.MALFORMED_RESPONSE
    }


def test_unknown_action_id_is_classified_separately_from_malformed_json() -> None:
    class Provider:
        async def plan_action(self, request):
            return {"action_id": "not-offered"}

    plan = asyncio.run(
        PrivateNpcAgentCoordinator(Provider()).plan_all((_request("a"),))
    )
    assert plan.failure_reasons["a"] is PrivateNpcAgentFailureReason.INVALID_ACTION_ID


@pytest.mark.parametrize("urgency", (-1, 1_000_000))
def test_minus_and_million_runtime_values_are_rejected(urgency: int) -> None:
    payload = _request("a").model_dump()
    payload["runtime_state"]["urgency"] = urgency
    with pytest.raises(ValueError):
        PrivateNpcAgentRequest.model_validate(payload)


def test_extra_patch_and_duplicate_actor_requests_are_rejected() -> None:
    payload = _request("a").model_dump()
    payload["state_patch"] = {"turn_number": 99}
    with pytest.raises(ValueError):
        PrivateNpcAgentRequest.model_validate(payload)
    with pytest.raises(ValueError):
        asyncio.run(PrivateNpcAgentCoordinator().plan_all((_request("a"), _request("a"))))


def test_timeout_falls_back_but_cancellation_propagates() -> None:
    class SlowProvider:
        async def plan_action(self, request):
            await asyncio.sleep(1)
            return {"action_id": request.actor_options.candidates[1].action_id}

    plan = asyncio.run(PrivateNpcAgentCoordinator(SlowProvider(), timeout_seconds=0.001).plan_all((_request("a"),)))
    assert plan.sources["a"] is PrivateNpcAgentSource.FALLBACK
    assert plan.failure_reasons["a"] is PrivateNpcAgentFailureReason.TIMEOUT

    async def cancelled() -> None:
        task = asyncio.create_task(PrivateNpcAgentCoordinator(SlowProvider()).plan_all((_request("a"),)))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancelled())


def test_adapter_keeps_each_request_private_and_uses_json_mode() -> None:
    class Client:
        async def generate(self, messages, **kwargs):
            self.messages, self.kwargs = messages, kwargs
            return SimpleNamespace(content=json.dumps({"action_id": "a-first"}))

    client = Client()
    asyncio.run(OpenRouterPrivateNpcAgentAdapter(client).plan_action(_request("a")))
    assert client.kwargs == {
        "max_tokens": 80,
        "temperature": 0.0,
        "json_mode": True,
        "task_role": "private_npc_action",
    }
    sent = "\n".join(message.content for message in client.messages)
    assert "actor_options" in sent and "private_facts" in sent
    assert "state_patch" not in sent
    assert "inert input data" in client.messages[0].content
