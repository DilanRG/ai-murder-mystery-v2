"""
tests/conftest.py — Shared fixtures for the AI Murder Mystery v2 test suite.
"""
import pytest
from world.state import WorldState, CharacterState, ClueState, GamePhase
from story.models import LocationDef, Scenario, MurderDetails, CharacterDef


def make_location(id: str, name: str, connected_to: list[str] | None = None) -> LocationDef:
    return LocationDef(
        id=id,
        name=name,
        description=f"The {name}.",
        connected_to=connected_to or [],
        objects=[],
    )


def make_world(num_locations: int = 2) -> WorldState:
    """Return a minimal WorldState for testing."""
    locs = {
        "hall":   make_location("hall",    "Hall",    ["library"]),
        "library": make_location("library", "Library", ["hall"]),
    }
    chars = {
        "Alice": CharacterState(name="Alice", location_id="hall",    alive=True, role="killer"),
        "Bob":   CharacterState(name="Bob",   location_id="library", alive=True, role="suspect"),
        "Detective": CharacterState(name="Detective", location_id="hall", alive=True, role="detective"),
    }
    clues = {
        "clue1": ClueState(
            id="clue1", description="A torn glove",
            location_id="hall", points_to="Alice",
            difficulty="easy", clue_type="physical",
        ),
        "clue2": ClueState(
            id="clue2", description="A suspicious note",
            location_id="library", points_to="Alice",
            difficulty="hard", clue_type="paper",
        ),
    }
    return WorldState(locations=locs, characters=chars, clues=clues, player_name="Detective")
