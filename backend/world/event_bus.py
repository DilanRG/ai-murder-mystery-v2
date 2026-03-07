"""
Event bus — routes GameEvents to the correct observers based on perception rules.
Perception rules from architecture §4.3:
  - Characters at the same location see normal/shout events
  - Characters at adjacent locations faintly hear shout events
  - Whisper events only go to the direct target
  - All events that the player can perceive are queued for WebSocket delivery
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


@dataclass
class GameEvent:
    """A single percievable event in the world."""
    event_type: str           # "movement" | "speech" | "discovery" | "examine" | "atmosphere"
    actor: str                # Who caused the event
    location: str             # Location ID where it occurred
    description: str          # Human-readable narrative
    data: dict[str, Any] = field(default_factory=dict)    # Type-specific payload
    timestamp: float = field(default_factory=time.time)
    volume: str = "normal"    # "normal" | "whisper" | "shout" (for speech events)
    target: str = ""          # For whisper/targeted events

    def to_client_dict(self) -> dict[str, Any]:
        return {
            "type": self.event_type,
            "actor": self.actor,
            "location": self.location,
            "description": self.description,
            "data": self.data,
            "timestamp": self.timestamp,
        }


# Type alias for async WebSocket sender
WSSender = Callable[[dict[str, Any]], Coroutine]


class EventBus:
    """
    Routes game events to:
    1. NPC agent perception queues (so agents can react on next tick)
    2. Player WebSocket connection (if the event is visible to the player)
    """

    def __init__(self, world_state_ref=None) -> None:
        # world_state is injected after construction to avoid circular imports
        self.world: Any = world_state_ref
        # Agent queues: agent_name → asyncio.Queue of GameEvent
        self._agent_queues: dict[str, asyncio.Queue] = {}
        # WebSocket sender (set by the WebSocket manager)
        self._ws_sender: WSSender | None = None

    def set_world(self, world) -> None:
        self.world = world

    def set_ws_sender(self, sender: WSSender) -> None:
        self._ws_sender = sender

    def register_agent(self, agent_name: str) -> asyncio.Queue:
        """Register an agent and return their perception queue."""
        q: asyncio.Queue = asyncio.Queue()
        self._agent_queues[agent_name] = q
        return q

    def unregister_agent(self, agent_name: str) -> None:
        self._agent_queues.pop(agent_name, None)

    async def emit(self, event: GameEvent) -> None:
        """
        Route a game event to all appropriate observers.
        Also records the event on world.events for the debrief timeline.
        """
        if not self.world:
            return

        # Record on world timeline (capped at 200 entries)
        if len(self.world.events) < 200:
            self.world.events.append(event)

        player_name = self.world.player_name
        player_loc = self.world.get_character_location(player_name)

        # Determine which agent names can perceive this event
        visible_to: set[str] = self._compute_visibility(event)

        # Push to agent queues
        for agent_name, queue in self._agent_queues.items():
            if agent_name in visible_to:
                await queue.put(event)

        # Push to player WebSocket if visible to player
        if player_loc is not None and self._ws_sender:
            player_can_see = player_loc in self._compute_player_visible_locations(event)
            if player_can_see:
                try:
                    await self._ws_sender({"type": event.event_type, "data": event.to_client_dict()})
                except Exception:
                    pass  # Drop if WebSocket is closed

    def _compute_visibility(self, event: GameEvent) -> set[str]:
        """Return names of all agents who can perceive this event."""
        visible: set[str] = set()
        if not self.world:
            return visible

        if event.event_type == "speech" and event.volume == "whisper":
            # Whisper: only the actor and direct target
            visible.add(event.actor)
            if event.target:
                visible.add(event.target)
            return visible

        # Normal and shout: everyone at the same location
        chars_at_location = self.world.get_characters_at(event.location)
        visible.update(chars_at_location)

        if event.volume == "shout":
            # Shout: also adjacent locations (faintly)
            for adj_id in self.world.get_adjacent_locations(event.location):
                visible.update(self.world.get_characters_at(adj_id))

        return visible

    def _compute_player_visible_locations(self, event: GameEvent) -> set[str]:
        """Return location IDs from which the player can perceive the event."""
        if not self.world:
            return set()

        if event.volume == "whisper" and event.target != self.world.player_name:
            return set()  # Player can't hear a whisper they're not part of

        locations = {event.location}
        if event.volume == "shout":
            locations.update(self.world.get_adjacent_locations(event.location))
        return locations

    def get_pending_events(self, agent_name: str) -> list[GameEvent]:
        """Drain all pending events for an agent (non-blocking)."""
        q = self._agent_queues.get(agent_name)
        if not q:
            return []
        events: list[GameEvent] = []
        while not q.empty():
            try:
                events.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events
