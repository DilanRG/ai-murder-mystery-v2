"""
tests/test_world.py — Unit tests for WorldState mutations and queries.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import pytest
from conftest import make_world
from world.state import ClueState


class TestMovement:
    def test_npc_can_move_to_adjacent_location(self):
        world = make_world()
        assert world.get_character_location("Alice") == "hall"
        result = world.move_character("Alice", "library")
        assert result is True
        assert world.get_character_location("Alice") == "library"

    def test_npc_cannot_move_to_non_adjacent_location(self):
        world = make_world()
        # hall and library are the only two locations; no location "vault"
        result = world.move_character("Alice", "vault")
        assert result is False
        assert world.get_character_location("Alice") == "hall"

    def test_player_can_move_freely(self):
        """Player ignores adjacency checks."""
        world = make_world()
        # Remove the hall→library connection to make it non-adjacent
        world.locations["hall"].connected_to = []
        result = world.move_player("library")
        assert result is True
        assert world.get_character_location("Detective") == "library"

    def test_presence_index_is_updated_on_move(self):
        world = make_world()
        assert "Alice" in world.get_characters_at("hall")
        world.move_character("Alice", "library")
        assert "Alice" not in world.get_characters_at("hall")
        assert "Alice" in world.get_characters_at("library")


class TestClueDiscovery:
    def test_discover_clue_marks_it_found(self):
        world = make_world()
        clue = world.discover_clue("clue1", "Detective")
        assert clue is not None
        assert clue.discovered is True
        assert clue.discovered_by == "Detective"

    def test_discover_clue_twice_returns_none(self):
        world = make_world()
        world.discover_clue("clue1", "Detective")
        result = world.discover_clue("clue1", "Bob")
        assert result is None

    def test_discovered_clue_not_in_get_clues_at(self):
        world = make_world()
        assert len(world.get_clues_at("hall")) == 1
        world.discover_clue("clue1", "Detective")
        assert len(world.get_clues_at("hall")) == 0


class TestPlantedEvidence:
    def test_planted_clue_is_findable(self):
        world = make_world()
        planted = ClueState(
            id="planted_abc",
            description="A fake bloody glove",
            location_id="library",
            points_to="Bob",
            difficulty="medium",
            clue_type="physical",
        )
        world.add_planted_clue(planted)
        assert "planted_abc" in world.clues
        assert world.clues["planted_abc"].planted is True
        # Should appear in get_clues_at for the location
        clues_in_lib = world.get_clues_at("library")
        assert any(c.id == "planted_abc" for c in clues_in_lib)


class TestElapsedTime:
    def test_elapsed_seconds_increases(self):
        world = make_world()
        t1 = world.elapsed_seconds
        time.sleep(0.05)
        t2 = world.elapsed_seconds
        assert t2 > t1
