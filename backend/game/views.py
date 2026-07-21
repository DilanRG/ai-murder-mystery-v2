"""Strict player-facing projections for the deterministic game engine.

These models intentionally do not mirror canonical content or runtime models.
Adding a field here is a visibility decision, not a serialization convenience.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from game.models import StrictModel


class PublicRoomView(StrictModel):
    id: str
    name: str
    description: str
    exits: list[str] = Field(default_factory=list)
    searchable_objects: list[dict[str, str]] = Field(default_factory=list)


class PublicCharacterView(StrictModel):
    id: str
    name: str
    description: str = ""
    portrait_url: str = ""
    emotional_state: str = Field(default="", max_length=80)


class PublicEvidenceView(StrictModel):
    id: str
    name: str
    description: str
    kind: str


class PublicFactView(StrictModel):
    """A canonical fact only after the runtime explicitly grants player knowledge."""

    id: str
    category: str
    statement: str


class PublicItemView(StrictModel):
    id: str
    name: str
    description: str


class PublicSceneActionView(StrictModel):
    """An authored scene interaction currently available in the player's room."""

    id: str
    label: str
    description: str


class PublicStatementView(StrictModel):
    id: str = ""
    turn: int = 0
    minute: int = 0
    speaker_id: str
    speaker_name: str
    text: str
    topic: str


class PublicTimelineEntryView(StrictModel):
    id: str
    minute: int | None = None
    text: str
    source_ids: list[str] = Field(default_factory=list)
    player_note: str = ""


class PublicContradictionView(StrictModel):
    id: str
    left_statement_id: str
    right_statement_id: str
    note: str = ""
    confirmed: bool = False


class PublicOpeningView(StrictModel):
    discoverer_id: str
    discoverer_name: str
    victim_id: str
    victim_name: str
    body_room_name: str
    body_condition: str
    discoverer_observations: list[str]
    containment_statement: str
    initial_reactions: list[PublicStatementView]


class PublicResultView(StrictModel):
    end_reason: Literal["accusation", "timeout"]
    accused_character_id: str | None
    correct_culprit: bool
    support_score: int
    method_supported: bool
    motive_supported: bool
    timeline_supported: bool
    evidence_supported: bool = False
    contradictions_supported: bool = False
    evaluation_score: int = 0
    selected_supporting_evidence_ids: list[str] = Field(default_factory=list)
    confirmed_contradiction_ids: list[str] = Field(default_factory=list)
    solved: bool
    summary: str


class PublicStoryPresentationView(StrictModel):
    source: str
    tagline: str
    public_opening: str
    atmosphere: str
    character_tensions: dict[str, str] = Field(default_factory=dict)
    room_flavour: dict[str, str] = Field(default_factory=dict)


class PlayerGameView(StrictModel):
    """The only complete game-state shape intended for a player or API client."""

    case_title: str
    story: PublicStoryPresentationView
    phase: str
    turn: int
    in_game_minute: int
    time_label: str
    player_room: PublicRoomView
    present_characters: list[PublicCharacterView] = Field(default_factory=list)
    suspects: list[PublicCharacterView] = Field(default_factory=list)
    discovered_evidence: list[PublicEvidenceView] = Field(default_factory=list)
    known_facts: list[PublicFactView] = Field(default_factory=list)
    inventory: list[PublicItemView] = Field(default_factory=list)
    available_scenes: list[PublicSceneActionView] = Field(default_factory=list)
    statements: list[PublicStatementView] = Field(default_factory=list)
    timeline: list[PublicTimelineEntryView] = Field(default_factory=list)
    contradictions: list[PublicContradictionView] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    opening: PublicOpeningView | None = None
    active_interview_character_id: str | None = None
    active_interview_exchanges_remaining: int | None = None
    result: PublicResultView | None = None


class TurnResultView(StrictModel):
    accepted: bool
    committed: bool
    narration: str
    discoveries: list[PublicEvidenceView] = Field(default_factory=list)
    items: list[PublicItemView] = Field(default_factory=list)
    dialogue: PublicStatementView | None = None
    events: list[str] = Field(default_factory=list)
    game: PlayerGameView


# A short alias makes it convenient for a route/UI to speak in terms of a
# complete turn result without importing the implementation module.
TurnResult = TurnResultView
