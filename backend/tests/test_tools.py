"""
tests/test_tools.py — Unit tests for agent tool execution.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import asyncio
from conftest import make_world
from world.event_bus import GameEvent
from agents.tools import execute_tool


# ── Helpers ──────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestMoveTool:
    def test_move_to_adjacent_emits_movement_event(self):
        world = make_world()
        event = run(execute_tool("Alice", "move_to", {"location_id": "library"}, world, "killer"))
        assert event is not None
        assert event.event_type == "movement"
        assert world.get_character_location("Alice") == "library"

    def test_move_to_non_adjacent_returns_none(self):
        world = make_world()
        world.locations["hall"].connected_to = []  # sever the connection
        event = run(execute_tool("Alice", "move_to", {"location_id": "library"}, world, "killer"))
        assert event is None
        assert world.get_character_location("Alice") == "hall"


class TestSpeakTool:
    def test_speak_emits_speech_event(self):
        world = make_world()
        event = run(execute_tool("Alice", "speak", {"message": "Hello there."}, world))
        assert event is not None
        assert event.event_type == "speech"
        assert "Hello there." in event.description

    def test_speak_empty_message_returns_none(self):
        world = make_world()
        event = run(execute_tool("Alice", "speak", {"message": ""}, world))
        assert event is None


class TestPlantEvidenceTool:
    def test_killer_can_plant_evidence(self):
        world = make_world()
        clue_count_before = len(world.clues)
        event = run(execute_tool(
            "Alice", "plant_evidence",
            {"description": "Forged letter", "implicates": "Bob"},
            world, "killer"
        ))
        assert event is not None
        assert event.event_type == "atmosphere"
        assert len(world.clues) == clue_count_before + 1

    def test_non_killer_cannot_plant_evidence(self):
        world = make_world()
        clue_count_before = len(world.clues)
        event = run(execute_tool(
            "Bob", "plant_evidence",
            {"description": "Forged letter", "implicates": "Alice"},
            world, "suspect"
        ))
        assert event is None
        assert len(world.clues) == clue_count_before


class TestExamineTool:
    def test_examine_can_discover_easy_clues(self):
        world = make_world()
        # clue1 is easy and at "hall" where Alice is
        event = run(execute_tool("Alice", "examine", {"focus": "the room"}, world))
        assert event is not None
        assert event.event_type == "examine"

    def test_unknown_tool_returns_none(self):
        world = make_world()
        event = run(execute_tool("Alice", "fly_to_moon", {}, world))
        assert event is None
