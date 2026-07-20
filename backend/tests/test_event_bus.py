"""
tests/test_event_bus.py — Unit tests for EventBus emission and WebSocket broadcast.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import pytest
from conftest import make_world
from world.event_bus import EventBus, GameEvent


def run(coro):
    return asyncio.run(coro)


class TestEventBusEmit:
    def test_emitted_event_is_recorded_on_world(self):
        world = make_world()
        bus = EventBus()
        bus.set_world(world)

        event = GameEvent(
            event_type="speech",
            actor="Alice",
            location="hall",
            description="Alice says something.",
        )
        run(bus.emit(event))

        assert len(world.events) == 1
        assert world.events[0].event_type == "speech"
        assert world.events[0].actor == "Alice"

    def test_events_capped_at_200(self):
        world = make_world()
        bus = EventBus()
        bus.set_world(world)

        for i in range(210):
            ev = GameEvent(
                event_type="movement",
                actor="Bob",
                location="library",
                description=f"Bob moves {i}.",
            )
            run(bus.emit(ev))

        assert len(world.events) <= 200

    def test_ws_sender_is_called_on_emit(self):
        world = make_world()
        received = []

        async def mock_sender(data):
            received.append(data)

        bus = EventBus()
        bus.set_world(world)
        bus.set_ws_sender(mock_sender)

        event = GameEvent(
            event_type="discovery",
            actor="Detective",
            location="hall",
            description="Found a clue.",
        )
        run(bus.emit(event))

        assert len(received) == 1
        payload = received[0]
        assert payload["type"] == "discovery"
