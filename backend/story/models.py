"""
Story data models — the structured output of the story generation pipeline.
These are the canonical data shapes used throughout the backend.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── Character definition (our custom format, replacing CharacterCard V2) ────

@dataclass
class CharacterDef:
    """
    A character definition loaded from backend/characters/*.json.
    This is our own lean format designed for the murder mystery agent system.
    Characters should be morally ambiguous, complex, and drawn from diverse walks of life.
    """
    id: str                           # Unique slug, matches filename (e.g. "lady_ashford")
    name: str                         # Full display name
    description: str                  # Physical appearance and background
    personality: str                  # Comma-separated traits (drives AI behavior)
    voice: str                        # How they speak — cadence, vocabulary, style
    background: str                   # History that shapes their morality and secrets
    opening_line: str                 # Their first spoken line on meeting the player
    dialogue_example: str            # Example exchange (teaches the LLM their voice)
    tags: list[str]                   # Searchable traits: "aristocrat", "loner", etc.
    possible_roles: list[str]         # "killer" | "victim" | "suspect" | "witness"
    default_location: str             # Where they typically start
    social_connections: list[str]    # Other character IDs they have relationships with
    secrets: list[str]                # Dark truths about them (LLM uses per-agent)
    moral_alignment: str             # e.g. "lawful-grey", "chaotic-neutral", "self-serving"
    notes: str = ""                  # Designer notes for the LLM / future agents


# ── Scenario elements ────────────────────────────────────────────────────────

@dataclass
class LocationDef:
    id: str
    name: str
    description: str                  # Atmospheric single paragraph
    connected_to: list[str]           # IDs of reachable locations
    objects: list[str] = field(default_factory=list)  # Examinable objects here


@dataclass
class ClueDef:
    id: str
    description: str                  # What you see/find
    location: str                     # Location ID where it sits
    points_to: str                    # Character name it implicates
    difficulty: str                   # "easy" | "medium" | "hard"
    clue_type: str                    # "physical" | "testimony" | "document" | "behavioral"
    is_red_herring: bool = False


@dataclass
class RedHerring:
    description: str                  # The misleading clue/lead
    implicates: str                   # Who it falsely points to
    truth: str                        # The real explanation


@dataclass
class MurderDetails:
    victim: str                       # Character name
    killer: str                       # Character name
    method: str                       # How the murder was committed
    motive: str                       # Why the killer did it
    time_of_death: str                # Narrative time (e.g. "between midnight and 1am")
    location_of_death: str            # Location ID
    cover_story: str                  # What the killer claims happened


@dataclass
class CharacterBriefing:
    """
    Per-character knowledge partition — what a specific NPC agent knows.
    Agents receive ONLY their own briefing, not others'.
    """
    character_name: str
    role: str                         # "killer" | "suspect" | "witness" | "victim"
    alibi: str                        # Their stated whereabouts
    true_whereabouts: str             # What actually happened (may differ from alibi)
    knowledge: list[str]              # Things they genuinely know about the murder
    secrets: list[str]                # Personal secrets unrelated to (or related to) the murder
    goals: list[str]                  # What they want to achieve during the investigation
    relationships: dict[str, str]     # Character name → how they feel about them
    initial_emotional_state: str      # Their mood at game start
    suspicions: str                   # Who they suspect and why (narrative form)
    # Killer-only fields
    murder_knowledge: Optional[str] = None   # Full truth of what the killer did
    frame_target: Optional[str] = None       # Who the killer intends to blame


@dataclass
class Scenario:
    """The complete generated scenario — the ground truth of the mystery."""
    title: str
    setting: str                      # One-line (e.g. "A remote manor house, 1930s England")
    atmosphere: str                   # Tone/mood description
    opening_narration: str            # Cinematic intro shown to the player
    backstory: str                    # Context behind the relationships and murder
    murder: MurderDetails
    locations: list[LocationDef]
    clues: list[ClueDef]
    red_herrings: list[RedHerring]
    character_briefings: dict[str, CharacterBriefing]  # character_name → briefing
    # Populated during cast selection
    cast: list[CharacterDef] = field(default_factory=list)
