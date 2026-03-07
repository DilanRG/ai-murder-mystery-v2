"""
World state — the in-memory ground truth for the entire game session.
All mutations go through WorldState methods, never directly.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from story.models import Scenario, LocationDef


class GamePhase(str, Enum):
    SETUP = "setup"
    PLAYING = "playing"
    ENDED = "ended"


@dataclass
class CharacterState:
    """Runtime state for a single character (NPC or player)."""
    name: str
    location_id: str
    alive: bool
    role: str                         # "killer" | "suspect" | "witness" | "victim" | "detective"
    emotional_state: str = "tense"
    suspicions: dict[str, int] = field(default_factory=dict)  # name → 0–100


@dataclass
class ClueState:
    """Runtime state for a single clue."""
    id: str
    description: str
    location_id: str
    points_to: str
    difficulty: str                   # "easy" | "medium" | "hard"
    clue_type: str
    is_red_herring: bool = False
    discovered: bool = False
    discovered_by: Optional[str] = None
    discovered_at: Optional[float] = None
    planted: bool = False             # True if the killer agent planted this


@dataclass
class WorldState:
    """
    Server-side ground truth. The single source of truth for game state.
    Agents and the player interact with the world via WorldState methods — never direct mutation.
    """
    locations: dict[str, LocationDef]          # id → LocationDef (static + presence set)
    characters: dict[str, CharacterState]      # name → CharacterState
    clues: dict[str, ClueState]                # id → ClueState
    events: list["GameEvent"] = field(default_factory=list)
    game_phase: GamePhase = GamePhase.SETUP
    game_clock_start: float = field(default_factory=time.time)
    player_name: str = ""

    # Dynamic character placements (location_id → set of character names)
    _presence: dict[str, set[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Build presence index from character states
        self._presence = {loc_id: set() for loc_id in self.locations}
        for char in self.characters.values():
            if char.location_id in self._presence:
                self._presence[char.location_id].add(char.name)

    # ── Queries ─────────────────────────────────────────────────────────────

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.game_clock_start

    def get_location(self, location_id: str) -> Optional[LocationDef]:
        return self.locations.get(location_id)

    def get_characters_at(self, location_id: str) -> set[str]:
        return self._presence.get(location_id, set())

    def get_character_location(self, name: str) -> Optional[str]:
        char = self.characters.get(name)
        return char.location_id if char else None

    def get_adjacent_locations(self, location_id: str) -> list[str]:
        loc = self.locations.get(location_id)
        return loc.connected_to if loc else []

    def get_clues_at(self, location_id: str) -> list[ClueState]:
        return [c for c in self.clues.values() if c.location_id == location_id and not c.discovered]

    def get_discovered_clues(self) -> list[ClueState]:
        return [c for c in self.clues.values() if c.discovered]

    # ── Mutations ────────────────────────────────────────────────────────────

    def move_character(self, name: str, to_location_id: str) -> bool:
        """Move a character to a new location. Returns True on success."""
        char = self.characters.get(name)
        if not char:
            return False
        if to_location_id not in self.locations:
            return False
        # Check adjacency (player moves freely; enforce for NPCs)
        current_loc = self.get_location(char.location_id)
        if current_loc and to_location_id not in current_loc.connected_to:
            return False  # Not reachable
        # Update presence index
        self._presence.get(char.location_id, set()).discard(name)
        self._presence.setdefault(to_location_id, set()).add(name)
        char.location_id = to_location_id
        return True

    def move_player(self, to_location_id: str) -> bool:
        """Move the player — ignores adjacency checks (player clicks map freely)."""
        char = self.characters.get(self.player_name)
        if not char or to_location_id not in self.locations:
            return False
        self._presence.get(char.location_id, set()).discard(self.player_name)
        self._presence.setdefault(to_location_id, set()).add(self.player_name)
        char.location_id = to_location_id
        return True

    def discover_clue(self, clue_id: str, discovered_by: str) -> Optional[ClueState]:
        """Mark a clue as discovered. Returns the clue or None if already found/missing."""
        clue = self.clues.get(clue_id)
        if not clue or clue.discovered:
            return None
        clue.discovered = True
        clue.discovered_by = discovered_by
        clue.discovered_at = time.time()
        return clue

    def add_planted_clue(self, clue: ClueState) -> None:
        """Add a killer-planted fake clue to the world."""
        clue.planted = True
        self.clues[clue.id] = clue
        # Deliberately NOT adding to presence index — planted clues are
        # discovered via normal get_clues_at() which filters by location_id

    def update_character_state(self, name: str, **kwargs) -> None:
        """Update mutable fields on a CharacterState (emotional_state, suspicions, etc)."""
        char = self.characters.get(name)
        if not char:
            return
        for key, value in kwargs.items():
            if hasattr(char, key):
                setattr(char, key, value)

    def to_client_dict(self, player_name: str) -> dict:
        """
        Serialize world state for the frontend client.
        Does NOT expose secrets or agent internal states.
        """
        player_loc = self.get_character_location(player_name) or ""
        return {
            "phase": self.game_phase.value,
            "elapsed_seconds": round(self.elapsed_seconds),
            "player_location": player_loc,
            "locations": [
                {
                    "id": loc_id,
                    "name": loc.name,
                    "description": loc.description,
                    "connected_to": loc.connected_to,
                    "objects": loc.objects,
                    "characters": list(self.get_characters_at(loc_id)),
                }
                for loc_id, loc in self.locations.items()
            ],
            "characters": [
                {
                    "name": c.name,
                    "location": c.location_id,
                    "alive": c.alive,
                    "emotional_state": c.emotional_state,
                    "is_player": c.name == player_name,
                }
                for c in self.characters.values()
            ],
            "clues_discovered": [
                {
                    "id": c.id,
                    "description": c.description,
                    "points_to": c.points_to,
                    "location": c.location_id,
                    "clue_type": c.clue_type,
                    "is_red_herring": c.is_red_herring,
                    "planted": c.planted,
                }
                for c in self.clues.values()
                if c.discovered
            ],
        }


def build_world_state(scenario: Scenario, player_name: str, player_start_location: str) -> WorldState:
    """Construct a WorldState from a generated scenario and player info."""
    # Locations — LocationDef is already a dataclass, adding clues_here attr
    locations: dict[str, LocationDef] = {}
    for loc in scenario.locations:
        locations[loc.id] = loc

    # Characters — everyone starts at their default location (from character card)
    characters: dict[str, CharacterState] = {}

    # Victim is dead from the start
    murder = scenario.murder
    victim_char_def = next(
        (c for c in scenario.cast if c.name == murder.victim), None
    )
    if victim_char_def:
        characters[murder.victim] = CharacterState(
            name=murder.victim,
            location_id=murder.location_of_death,
            alive=False,
            role="victim",
            emotional_state="deceased",
        )

    for char_def in scenario.cast:
        if char_def.name == murder.victim:
            continue  # Already handled above
        briefing = scenario.character_briefings.get(char_def.name)
        role = briefing.role if briefing else "suspect"
        characters[char_def.name] = CharacterState(
            name=char_def.name,
            location_id=char_def.default_location,
            alive=True,
            role=role,
            emotional_state=briefing.initial_emotional_state if briefing else "tense",
        )

    # Player character
    characters[player_name] = CharacterState(
        name=player_name,
        location_id=player_start_location,
        alive=True,
        role="detective",
    )

    # Clues
    clues: dict[str, ClueState] = {}
    for c in scenario.clues:
        clues[c.id] = ClueState(
            id=c.id,
            description=c.description,
            location_id=c.location,
            points_to=c.points_to,
            difficulty=c.difficulty,
            clue_type=c.clue_type,
            is_red_herring=c.is_red_herring,
        )

    return WorldState(
        locations=locations,
        characters=characters,
        clues=clues,
        player_name=player_name,
    )
