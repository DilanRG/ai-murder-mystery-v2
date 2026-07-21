"""Generated cases spawn seven separately partitioned NPC planning calls."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from conftest import generated_stage_response, make_dummy_generated_document
from game.actions import AdvanceOpeningIntent, MoveIntent
from game.case_generation import compile_generated_scenario
from game.content import load_case, load_location
from game.engine import GameEngine
from game.service import GameService


def _generated_engine() -> GameEngine:
    source = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    generated = compile_generated_scenario(
        make_dummy_generated_document(),
        character_ids=source.character_ids,
        location=location,
        seed=84,
    )
    return GameEngine(
        generated.case,
        location,
        story_presentation=generated.presentation,
    )


def test_preview_partitions_exactly_one_private_briefing_per_survivor() -> None:
    engine = _generated_engine()
    engine.apply(AdvanceOpeningIntent())
    preview = engine.preview(MoveIntent(room_id=engine.view().player_room.exits[0]))

    requests = preview.private_npc_requests
    assert requests is not None and len(requests) == 7
    assert len({request.actor_id for request in requests}) == 7
    assert len({request.snapshot.model_dump_json() for request in requests}) == 1
    murderer_id = engine.case.murder.murderer_id
    for request in requests:
        assert request.actor_options.actor_id == request.actor_id
        private_fact_ids = {fact.id for fact in request.private_briefing.private_facts}
        if request.actor_id == murderer_id:
            assert "host_murder_truth" in private_fact_ids
            assert "Assigned role: murderer" in request.private_briefing.character_summary
        else:
            assert "host_murder_truth" not in private_fact_ids
            assert "Assigned role: innocent" in request.private_briefing.character_summary
        serialized = request.model_dump_json()
        for other_id, overlay in engine.case.overlays.items():
            if other_id == request.actor_id:
                continue
            assert overlay.private_motive not in serialized
            for secret in overlay.secrets:
                assert secret not in serialized


class _ScenarioThenAgentsProvider:
    def __init__(self) -> None:
        self.scenario_calls = 0
        self.agent_requests: list[dict[str, object]] = []

    async def generate(self, messages, **kwargs):
        system = messages[0].content
        if "canonical scenario architect" in system:
            self.scenario_calls += 1
            return SimpleNamespace(
                content=json.dumps(
                    generated_stage_response(
                        make_dummy_generated_document(), kwargs["task_role"]
                    )
                )
            )
        request = json.loads(messages[-1].content)
        self.agent_requests.append(request)
        return SimpleNamespace(
            content=json.dumps(
                {"action_id": request["actor_options"]["candidates"][0]["action_id"]}
            )
        )


class _ScenarioOnlyProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        assert "canonical scenario architect" in messages[0].content
        return SimpleNamespace(
            content=json.dumps(
                generated_stage_response(make_dummy_generated_document(), kwargs["task_role"])
            )
        )


class _NpcOnlyProvider:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    async def generate(self, messages, **kwargs):
        assert "canonical scenario architect" not in messages[0].content
        request = json.loads(messages[-1].content)
        self.requests.append(request)
        return SimpleNamespace(
            content=json.dumps(
                {"action_id": request["actor_options"]["candidates"][0]["action_id"]}
            )
        )


def test_generated_committed_turn_runs_seven_isolated_agent_calls(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        source = load_case("ashwick_sample")
        provider = _ScenarioThenAgentsProvider()
        service = GameService(tmp_path, llm=provider)
        await service.start_generated_async(
            seed=84,
            character_ids=source.character_ids,
        )
        await service.action(AdvanceOpeningIntent())
        destination = service.state().player_room.exits[0]

        result = await service.action(MoveIntent(room_id=destination))

        assert result["accepted"] and result["committed"]
        assert provider.scenario_calls == 4
        assert len(provider.agent_requests) == 7
        assert len({request["actor_id"] for request in provider.agent_requests}) == 7
        assert all(
            isinstance(request["actor_options"], dict)
            for request in provider.agent_requests
        )
        assert len(
            {
                json.dumps(request["snapshot"], sort_keys=True)
                for request in provider.agent_requests
            }
        ) == 1
        history = service.engine.action_history
        assert history is not None
        assert len(history[-1].npc_action_ids) == 7

    asyncio.run(scenario())


def test_generated_case_and_runtime_can_use_distinct_role_clients(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        source = load_case("ashwick_sample")
        scenario_provider = _ScenarioOnlyProvider()
        npc_provider = _NpcOnlyProvider()
        service = GameService(
            tmp_path,
            scenario_llm=scenario_provider,
            npc_llm=npc_provider,
        )

        await service.start_generated_async(
            seed=84,
            character_ids=source.character_ids,
        )
        await service.action(AdvanceOpeningIntent())
        destination = service.state().player_room.exits[0]
        result = await service.action(MoveIntent(room_id=destination))

        assert result["accepted"] and result["committed"]
        assert scenario_provider.calls == 4
        assert len(npc_provider.requests) == 7
        assert len({request["actor_id"] for request in npc_provider.requests}) == 7
        diagnostics = service.runtime_diagnostics()
        assert len(diagnostics) == 7
        assert all(item["task_role"] == "private_npc_action" for item in diagnostics)
        assert all(item["source"] == "provider" for item in diagnostics)
        assert all(item["failure_reason"] is None for item in diagnostics)

    asyncio.run(scenario())
