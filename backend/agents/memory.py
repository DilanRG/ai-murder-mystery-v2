"""
Agent memory model — what an NPC remembers and accumulates during the game.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationTurn:
    speaker: str          # who spoke
    message: str          # what they said
    timestamp: float = 0.0


@dataclass
class AgentMemory:
    """
    Runtime memory for a single NPC agent.
    Grows as the game progresses — agents accumulate observations,
    dialogue history, and updated suspicions.
    """
    character_name: str

    # All dialogue this agent has participated in OR overheard
    conversation_log: list[ConversationTurn] = field(default_factory=list)

    # Events this agent perceived via the event bus (narrated strings)
    witnessed_events: list[str] = field(default_factory=list)

    # Per-character suspicion levels and reasoning (name → (0–100, reason))
    suspicions: dict[str, tuple[int, str]] = field(default_factory=dict)

    # Short notes the agent has formed internally (updated by LLM reasoning)
    internal_notes: list[str] = field(default_factory=list)

    # Track what locations they've visited
    visited_locations: set[str] = field(default_factory=set)

    # Whether they've been directly questioned by the player
    questioned_by_player: bool = False

    def add_conversation(self, speaker: str, message: str, timestamp: float = 0.0) -> None:
        self.conversation_log.append(ConversationTurn(speaker, message, timestamp))

    def add_witnessed_event(self, description: str) -> None:
        # Cap to last 30 events to keep prompt size manageable
        self.witnessed_events.append(description)
        if len(self.witnessed_events) > 30:
            self.witnessed_events = self.witnessed_events[-30:]

    def get_recent_conversation(self, max_turns: int = 20) -> list[ConversationTurn]:
        """Return the last N turns of conversation log."""
        return self.conversation_log[-max_turns:]

    def format_witnessed_events(self) -> str:
        if not self.witnessed_events:
            return "Nothing unusual observed so far."
        return "\n".join(f"- {e}" for e in self.witnessed_events[-15:])

    def format_suspicions(self) -> str:
        if not self.suspicions:
            return "No strong suspicions formed yet."
        lines = []
        for name, (level, reason) in self.suspicions.items():
            bar = "▓" * (level // 10) + "░" * (10 - level // 10)
            lines.append(f"- {name}: [{bar}] {level}/100 — {reason}")
        return "\n".join(lines)
