"""Typed, transport-independent player commands for the turn engine."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import AliasChoices, Field, TypeAdapter, field_validator

from game.models import (
    MAX_ACTION_CLAIM_LENGTH,
    MAX_ACTION_ID_REFERENCES,
    StrictModel,
)


class PlayerIntentBase(StrictModel):
    """Every command is an explicit, discriminated request to the engine."""

    kind: str


class AdvanceOpeningIntent(PlayerIntentBase):
    kind: Literal["advance_opening"] = "advance_opening"


class MoveIntent(PlayerIntentBase):
    kind: Literal["move"] = "move"
    room_id: str = Field(validation_alias=AliasChoices("room_id", "destination_room_id"))


class SearchIntent(PlayerIntentBase):
    kind: Literal["search"] = "search"
    object_id: str


class BeginInterviewIntent(PlayerIntentBase):
    kind: Literal["begin_interview"] = "begin_interview"
    character_id: str


class InterviewExchangeIntent(PlayerIntentBase):
    kind: Literal["interview_exchange"] = "interview_exchange"
    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        stripped = value.strip()
        if not 1 <= len(stripped) <= 1_200:
            raise ValueError("interview message must contain 1 to 1200 non-whitespace characters")
        return stripped


class EndInterviewIntent(PlayerIntentBase):
    kind: Literal["end_interview"] = "end_interview"


class ExamineEvidenceIntent(PlayerIntentBase):
    kind: Literal["examine_evidence"] = "examine_evidence"
    evidence_id: str


class ExamineSceneIntent(PlayerIntentBase):
    """Inspect an authored scene route, currently the publicly known body."""

    kind: Literal["examine_scene"] = "examine_scene"
    scene_id: str = Field(default="body", validation_alias=AliasChoices("scene_id", "target_id"))


class ExamineBodyIntent(PlayerIntentBase):
    """Convenience spelling for clients that model the body as its own action."""

    kind: Literal["examine_body"] = "examine_body"


class ReviewNotebookIntent(PlayerIntentBase):
    """A deliberately free action: it changes no authoritative world state."""

    kind: Literal["review_notebook"] = "review_notebook"


class AddNoteIntent(PlayerIntentBase):
    kind: Literal["add_note"] = "add_note"
    text: str = Field(min_length=1, max_length=1_000)


class AddTimelineEntryIntent(PlayerIntentBase):
    kind: Literal["add_timeline_entry"] = "add_timeline_entry"
    text: str = Field(min_length=1, max_length=1_000)
    minute: int | None = Field(default=None, ge=0)
    source_ids: list[str] = Field(default_factory=list, max_length=MAX_ACTION_ID_REFERENCES)


class MarkContradictionIntent(PlayerIntentBase):
    kind: Literal["mark_contradiction"] = "mark_contradiction"
    left_statement_id: str = Field(validation_alias=AliasChoices("left_statement_id", "statement_id_a"))
    right_statement_id: str = Field(validation_alias=AliasChoices("right_statement_id", "statement_id_b"))
    note: str = Field(default="", max_length=1_000)


class AccuseIntent(PlayerIntentBase):
    kind: Literal["accuse"] = "accuse"
    character_id: str = Field(
        validation_alias=AliasChoices("character_id", "accused_character_id", "culprit_id")
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=MAX_ACTION_ID_REFERENCES,
        validation_alias=AliasChoices(
            "evidence_ids",
            "selected_evidence_ids",
            "selected_supporting_evidence_ids",
        ),
    )
    method: str = Field(default="", max_length=MAX_ACTION_CLAIM_LENGTH)
    motive: str = Field(default="", max_length=MAX_ACTION_CLAIM_LENGTH)
    timeline: str = Field(default="", max_length=MAX_ACTION_CLAIM_LENGTH)
    method_evidence_ids: list[str] = Field(default_factory=list, max_length=MAX_ACTION_ID_REFERENCES)
    motive_evidence_ids: list[str] = Field(default_factory=list, max_length=MAX_ACTION_ID_REFERENCES)
    opportunity_evidence_ids: list[str] = Field(default_factory=list, max_length=MAX_ACTION_ID_REFERENCES)
    timeline_evidence_ids: list[str] = Field(default_factory=list, max_length=MAX_ACTION_ID_REFERENCES)
    timeline_fact_ids: list[str] = Field(default_factory=list, max_length=MAX_ACTION_ID_REFERENCES)
    confirmed_contradiction_ids: list[str] = Field(
        default_factory=list,
        max_length=MAX_ACTION_ID_REFERENCES,
    )


# ``AccusationIntent`` reads more naturally at call sites while preserving the
# short wire-level command name used in JSON payloads.
AccusationIntent = AccuseIntent

PlayerIntent = Annotated[
    Union[
        AdvanceOpeningIntent,
        MoveIntent,
        SearchIntent,
        BeginInterviewIntent,
        InterviewExchangeIntent,
        EndInterviewIntent,
        ExamineEvidenceIntent,
        ExamineSceneIntent,
        ExamineBodyIntent,
        ReviewNotebookIntent,
        AddNoteIntent,
        AddTimelineEntryIntent,
        MarkContradictionIntent,
        AccuseIntent,
    ],
    Field(discriminator="kind"),
]

PLAYER_INTENT_ADAPTER = TypeAdapter(PlayerIntent)


def parse_player_intent(value: PlayerIntent | dict[str, object]) -> PlayerIntent:
    """Validate an untrusted JSON command as one of the supported intents."""
    return PLAYER_INTENT_ADAPTER.validate_python(value)
