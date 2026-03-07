"""
Agent perception — constructs a filtered, honest world view for each NPC.

Perception rules (from architecture §4.3):
  - An agent sees characters and events AT their current location
  - They faintly know about events in ADJACENT locations (shouts only)
  - They have NO visibility into non-adjacent locations
  - They remember what they personally witnessed over time (via AgentMemory)
"""
from __future__ import annotations
from dataclasses import dataclass
from world.state import WorldState


@dataclass
class AgentPerception:
    """What an NPC agent currently perceives."""
    agent_name: str
    current_location_id: str
    current_location_name: str
    current_location_description: str
    current_location_objects: list[str]

    # Who else is here right now
    characters_present: list[str]       # names, excluding self

    # What the agent can detect about adjacent rooms
    adjacent_locations: list[dict]      # [{"id", "name", "char_count"}]

    # Undiscovered clues visible in the current room
    clues_visible: list[str]            # clue descriptions

    # Emotional state of others in the room (name → stated emotional_state)
    emotional_atmosphere: dict[str, str]

    def format_for_prompt(self) -> str:
        """Format perception into a concise prompt-ready block."""
        lines = [
            f"CURRENT LOCATION: {self.current_location_name}",
            f"  {self.current_location_description}",
        ]
        if self.current_location_objects:
            lines.append(f"  Objects here: {', '.join(self.current_location_objects)}")
        if self.characters_present:
            lines.append(f"  People here with you: {', '.join(self.characters_present)}")
            atm = [f"{n} ({s})" for n, s in self.emotional_atmosphere.items() if n in self.characters_present]
            if atm:
                lines.append(f"  Their demeanour: {'; '.join(atm)}")
        else:
            lines.append("  No one else is here right now.")
        if self.clues_visible:
            lines.append("  You notice: " + "; ".join(self.clues_visible[:3]))
        if self.adjacent_locations:
            adj_parts = []
            for loc in self.adjacent_locations:
                crowd = f" ({loc['char_count']} people)" if loc["char_count"] else ""
                adj_parts.append(f"{loc['name']}{crowd}")
            lines.append(f"ADJACENT ROOMS: {', '.join(adj_parts)}")
        return "\n".join(lines)


def get_perception(agent_name: str, world: WorldState) -> AgentPerception:
    """Build a fresh AgentPerception for an agent from the current world state."""
    loc_id = world.get_character_location(agent_name) or ""
    loc = world.get_location(loc_id)

    characters_present = [
        name for name in world.get_characters_at(loc_id)
        if name != agent_name
    ]

    # Clues visible in this room (undiscovered, easy/medium — hard ones need investigation)
    clues_visible = []
    for clue in world.get_clues_at(loc_id):
        if clue.difficulty in ("easy", "medium"):
            clues_visible.append(clue.description)

    # Emotional atmosphere of other characters here
    emotional_atmosphere = {}
    for name in characters_present:
        char = world.characters.get(name)
        if char:
            emotional_atmosphere[name] = char.emotional_state

    # Adjacent location info (name + how many visible people are there)
    adjacent: list[dict] = []
    for adj_id in world.get_adjacent_locations(loc_id):
        adj_loc = world.get_location(adj_id)
        if adj_loc:
            adjacent.append({
                "id": adj_id,
                "name": adj_loc.name,
                "char_count": len(world.get_characters_at(adj_id)),
            })

    return AgentPerception(
        agent_name=agent_name,
        current_location_id=loc_id,
        current_location_name=loc.name if loc else loc_id,
        current_location_description=loc.description if loc else "",
        current_location_objects=loc.objects if loc else [],
        characters_present=characters_present,
        adjacent_locations=adjacent,
        clues_visible=clues_visible,
        emotional_atmosphere=emotional_atmosphere,
    )
