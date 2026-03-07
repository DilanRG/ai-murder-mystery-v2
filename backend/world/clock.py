"""
Game clock — controls the pacing of the simulation.

Supports three modes:
  - NONE: no time limit; the game runs until the player makes an accusation
  - REALTIME: countdown clock (e.g. 30 minutes of real time)
  - EVENT_DRIVEN: the endgame is triggered when the killer achieves a goal
                  or a critical event fires (e.g. killer attempts to flee)

The clock also controls the NPC agent tick rate (adaptive):
  - Base tick: 15s between agent actions
  - Active tick (2+ people in room): 10s
  - Idle tick (agent alone for multiple ticks): up to 30s
"""
from __future__ import annotations
import asyncio
import logging
import time
from enum import Enum
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class TimerMode(str, Enum):
    NONE = "none"
    REALTIME = "realtime"
    EVENT_DRIVEN = "event"


class GameClock:
    """
    Manages game timing and provides adaptive tick rates for agent loops.
    """

    # Base tick intervals (seconds)
    TICK_ACTIVE = 10     # Someone is talking / in same room
    TICK_BASE   = 18     # Normal agent idle
    TICK_IDLE   = 30     # Agent alone, nothing happening

    def __init__(
        self,
        mode: TimerMode = TimerMode.NONE,
        limit_seconds: float = 0.0,
        on_time_up: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.mode = mode
        self.limit_seconds = limit_seconds
        self.on_time_up = on_time_up
        self._start_time: float = time.time()
        self._paused = False
        self._pause_start: float = 0.0
        self._pause_accumulated: float = 0.0
        self._timer_task: asyncio.Task | None = None

    def start(self) -> None:
        self._start_time = time.time()
        if self.mode == TimerMode.REALTIME and self.limit_seconds > 0:
            self._timer_task = asyncio.create_task(self._countdown())

    def pause(self) -> None:
        if not self._paused:
            self._paused = True
            self._pause_start = time.time()

    def resume(self) -> None:
        if self._paused:
            self._pause_accumulated += time.time() - self._pause_start
            self._paused = False

    def stop(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    @property
    def elapsed_seconds(self) -> float:
        paused_extra = (time.time() - self._pause_start) if self._paused else 0.0
        return time.time() - self._start_time - self._pause_accumulated - paused_extra

    @property
    def remaining_seconds(self) -> float:
        if self.mode != TimerMode.REALTIME or self.limit_seconds <= 0:
            return -1.0
        return max(0.0, self.limit_seconds - self.elapsed_seconds)

    @property
    def is_expired(self) -> bool:
        if self.mode != TimerMode.REALTIME or self.limit_seconds <= 0:
            return False
        return self.elapsed_seconds >= self.limit_seconds

    def get_agent_tick(self, chars_in_room: int) -> float:
        """Return the recommended sleep duration for an agent in their current context."""
        if chars_in_room > 1:
            return self.TICK_ACTIVE
        return self.TICK_BASE

    async def _countdown(self) -> None:
        """Background task — fires on_time_up when the clock expires."""
        try:
            await asyncio.sleep(self.limit_seconds)
            if self.on_time_up:
                await self.on_time_up()
        except asyncio.CancelledError:
            pass
