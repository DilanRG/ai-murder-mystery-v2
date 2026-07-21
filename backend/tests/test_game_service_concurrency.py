"""Concurrency regressions for previewed provider planning."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from game.actions import AdvanceOpeningIntent, MoveIntent
from game.service import GameService


class _BlockingPlannerClient:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, messages, **kwargs):
        request = json.loads(messages[-1].content)
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(
            content=json.dumps(
                {
                    "selections": [
                        {
                            "actor_id": actor["actor_id"],
                            "action_id": actor["candidates"][0]["action_id"],
                        }
                        for actor in request["actor_options"]
                    ]
                }
            )
        )


def test_new_session_waits_for_an_in_flight_planned_action(tmp_path: Path) -> None:
    async def scenario() -> None:
        llm = _BlockingPlannerClient()
        service = GameService(tmp_path, llm=llm)
        service.start()
        service.engine.apply(AdvanceOpeningIntent())
        destination = service.state().player_room.exits[0]

        action_task = asyncio.create_task(
            service.action(MoveIntent(room_id=destination))
        )
        await llm.started.wait()
        reset_task = asyncio.create_task(service.start_async())
        await asyncio.sleep(0)
        assert not reset_task.done()

        llm.release.set()
        action_result = await action_task
        assert action_result["accepted"] and action_result["committed"]
        reset_view = await reset_task
        assert reset_view.phase == "discovery"
        assert reset_view.turn == 0
        assert service.state() == reset_view

    asyncio.run(scenario())


def test_cancelled_planner_leaves_original_runtime_untouched(tmp_path: Path) -> None:
    async def scenario() -> None:
        llm = _BlockingPlannerClient()
        service = GameService(tmp_path, llm=llm)
        service.start()
        service.engine.apply(AdvanceOpeningIntent())
        before = service.engine.runtime.model_copy(deep=True)
        destination = service.state().player_room.exits[0]

        action_task = asyncio.create_task(
            service.action(MoveIntent(room_id=destination))
        )
        await llm.started.wait()
        action_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await action_task

        assert service.engine.runtime == before
        reset = await service.start_async()
        assert reset.phase == "discovery"

    asyncio.run(scenario())
