"""Canonical schemas for the turn-based murder-mystery game.

The models deliberately separate immutable authored truth from mutable runtime
state and from player-visible knowledge. API routes must never serialize a
``CaseDefinition`` directly to the player.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenDict(dict):
    """A JSON-serializable dictionary that rejects every mutating operation."""

    @staticmethod
    def _immutable(*args: Any, **kwargs: Any) -> None:
        raise TypeError("canonical game content is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _deep_freeze(value: Any) -> Any:
    """Recursively freeze collection fields after Pydantic validation."""
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, dict):
        return FrozenDict({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_deep_freeze(item) for item in value)
    return value


class StrictModel(BaseModel):
    """Base for validated JSON documents and mutable runtime records."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FrozenModel(StrictModel):
    """Base for immutable authored content and canonical case truth."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    @model_validator(mode="after")
    def freeze_nested_collections(self) -> "FrozenModel":
        for field_name in type(self).model_fields:
            object.__setattr__(
                self, field_name, _deep_freeze(getattr(self, field_name))
            )
        extra = getattr(self, "__pydantic_extra__", None)
        if extra:
            object.__setattr__(self, "__pydantic_extra__", _deep_freeze(extra))
        return self


MAX_NOTEBOOK_RECORDS = 128
MAX_ACTION_ID_REFERENCES = 64
MAX_ACTION_CLAIM_LENGTH = 2_000
MAX_CONVERSATION_MEMORIES = 256
BoundedNote = Annotated[str, Field(min_length=1, max_length=1_000)]
BoundedIdentifier = Annotated[str, Field(min_length=1, max_length=100)]


class CharacterRole(str, Enum):
    VICTIM = "victim"
    MURDERER = "murderer"
    INNOCENT = "innocent"


class AlibiType(str, Enum):
    TRUE = "true"
    FALSE = "false"
    INCOMPLETE = "incomplete"


class EvidenceKind(str, Enum):
    PHYSICAL = "physical"
    TESTIMONIAL = "testimonial"
    DOCUMENTARY = "documentary"
    BEHAVIOURAL = "behavioural"


class EvidenceCondition(str, Enum):
    IN_PLACE = "in_place"
    MOVED = "moved"
    CONCEALED = "concealed"
    DESTROYED = "destroyed"
    COLLECTED = "collected"


class GamePhase(str, Enum):
    DISCOVERY = "discovery"
    INVESTIGATION = "investigation"
    ENDED = "ended"


class FactCategory(str, Enum):
    IDENTITY = "identity"
    MOTIVE = "motive"
    MEANS = "means"
    OPPORTUNITY = "opportunity"
    TIMELINE = "timeline"
    ALIBI = "alibi"
    SECRET = "secret"
    CONTEXT = "context"


class TimelineEventType(str, Enum):
    SCHEDULE = "schedule"
    OBSERVATION = "observation"
    MURDER = "murder"
    DISCOVERY = "discovery"
    MEETING = "meeting"


class SearchDifficulty(int, Enum):
    OBVIOUS = 1
    CAREFUL = 2
    HIDDEN = 3


# ── Character Card V3-compatible content ────────────────────────────────────


class CharacterAssets(FrozenModel):
    portrait: str = ""
    expressions: dict[str, str] = Field(default_factory=dict)


class MurderMysteryCardExtension(FrozenModel):
    """Game-specific static fields stored below ``extensions.murder_mystery``."""

    identity: str
    public_biography: str
    appearance: str
    speaking_style: str
    values: tuple[str, ...]
    fears: tuple[str, ...]
    habits: tuple[str, ...]
    flaws: tuple[str, ...]
    vulnerabilities: tuple[str, ...]
    social_behaviour: str
    conflict_behaviour: str
    deception_tendency: str
    disclosure_tendency: str
    emotional_response_rules: tuple[str, ...]
    relationship_compatibility: tuple[str, ...]
    motive_hooks: tuple[str, ...]
    secret_hooks: tuple[str, ...]
    behavioural_constraints: tuple[str, ...]
    assets: CharacterAssets = Field(default_factory=CharacterAssets)


class CardExtensions(FrozenModel):
    model_config = ConfigDict(
        extra="allow", str_strip_whitespace=True, frozen=True
    )

    murder_mystery: MurderMysteryCardExtension


class CharacterCardAsset(FrozenModel):
    """Standard CCv3 asset reference."""

    type: str
    uri: str
    name: str
    ext: str


class LorebookEntry(FrozenModel):
    """Character Card V3 lorebook entry."""

    keys: tuple[str, ...]
    content: str
    extensions: dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    insertion_order: int
    use_regex: bool
    constant: bool | None = None
    name: str | None = None
    priority: int | None = None
    id: int | str | None = None
    comment: str | None = None
    case_sensitive: bool | None = None
    selective: bool | None = None
    secondary_keys: tuple[str, ...] = Field(default_factory=tuple)
    position: Literal["before_char", "after_char"] | None = None


class CharacterLorebook(FrozenModel):
    name: str | None = None
    description: str | None = None
    scan_depth: int | None = Field(default=None, ge=0)
    token_budget: int | None = Field(default=None, ge=0)
    recursive_scanning: bool | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)
    entries: tuple[LorebookEntry, ...]


class CharacterCardData(FrozenModel):
    name: str
    description: str
    personality: str
    scenario: str = ""
    first_mes: str
    mes_example: str
    creator_notes: str = ""
    system_prompt: str = ""
    post_history_instructions: str = ""
    alternate_greetings: tuple[str, ...] = Field(default_factory=tuple)
    group_only_greetings: tuple[str, ...] = Field(default_factory=tuple)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    creator: str = "AI Murder Mystery"
    character_version: str = "1.0"
    extensions: CardExtensions
    character_book: CharacterLorebook | None = None
    assets: tuple[CharacterCardAsset, ...] = Field(default_factory=tuple)
    nickname: str | None = None
    creator_notes_multilingual: dict[str, str] = Field(default_factory=dict)
    source: tuple[str, ...] = Field(default_factory=tuple)
    creation_date: int | None = None
    modification_date: int | None = None

    @model_validator(mode="after")
    def validate_main_icon(self) -> "CharacterCardData":
        icons = [asset for asset in self.assets if asset.type == "icon"]
        if icons and sum(asset.name == "main" for asset in icons) != 1:
            raise ValueError("CCv3 icon assets must contain exactly one named 'main'")
        return self


class GameCharacterCard(FrozenModel):
    """A JSON-compatible subset of Character Card V3 plus game extensions."""

    spec: Literal["chara_card_v3"] = "chara_card_v3"
    spec_version: Literal["3.0"] = "3.0"
    data: CharacterCardData


# ── Predefined location packages ────────────────────────────────────────────


class VisualTheme(FrozenModel):
    background: str
    surface: str
    accent: str
    danger: str
    text: str
    backdrop_asset: str = ""


class RoomDefinition(FrozenModel):
    id: str
    name: str
    short_name: str
    description: str
    atmosphere: str
    searchable_object_ids: tuple[str, ...] = Field(default_factory=tuple)
    body_discovery_allowed: bool = False
    tags: tuple[str, ...] = Field(default_factory=tuple)


class DoorDefinition(FrozenModel):
    id: str
    room_a_id: str
    room_b_id: str
    travel_minutes: int = Field(default=10, ge=0, le=60)
    locked_by_default: bool = False
    key_item_id: str | None = None
    one_way: bool = False


class SearchableObjectDefinition(FrozenModel):
    id: str
    room_id: str
    name: str
    description: str
    search_text: str
    difficulty: SearchDifficulty = SearchDifficulty.CAREFUL
    evidence_slot_ids: tuple[str, ...] = Field(default_factory=tuple)
    requires_item_id: str | None = None
    tags: tuple[str, ...] = Field(default_factory=tuple)


class EvidenceSlotDefinition(FrozenModel):
    id: str
    room_id: str
    object_id: str
    description: str
    capacity: int = Field(default=1, ge=1, le=10)


class PotentialWeaponDefinition(FrozenModel):
    id: str
    room_id: str
    object_id: str
    name: str
    description: str
    compatible_methods: tuple[str, ...]


class ItemDefinition(FrozenModel):
    id: str
    name: str
    description: str
    initial_slot_id: str | None = None
    portable: bool = True
    access_object_ids: tuple[str, ...] = Field(default_factory=tuple)
    access_door_ids: tuple[str, ...] = Field(default_factory=tuple)


class MurderOpportunityRule(FrozenModel):
    id: str
    room_ids: tuple[str, ...]
    compatible_methods: tuple[str, ...]
    weapon_ids: tuple[str, ...]
    access_summary: str
    witness_risk: str


class LocationEventDefinition(FrozenModel):
    id: str
    name: str
    trigger: str
    description: str
    engine_effect: str


class LocationPackage(FrozenModel):
    schema_version: Literal[1] = 1
    id: str
    name: str
    subtitle: str
    description: str
    isolation_premise: str
    assembly_room_id: str
    rooms: dict[str, RoomDefinition]
    doors: tuple[DoorDefinition, ...]
    searchable_objects: dict[str, SearchableObjectDefinition]
    evidence_slots: dict[str, EvidenceSlotDefinition]
    potential_weapons: dict[str, PotentialWeaponDefinition]
    items: dict[str, ItemDefinition] = Field(default_factory=dict)
    murder_opportunity_rules: tuple[MurderOpportunityRule, ...]
    body_discovery_room_ids: tuple[str, ...]
    movement_constraints: tuple[str, ...] = Field(default_factory=tuple)
    events: tuple[LocationEventDefinition, ...] = Field(default_factory=tuple)
    visual_theme: VisualTheme


# ── Immutable case truth ─────────────────────────────────────────────────────


class FactDefinition(FrozenModel):
    id: str
    category: FactCategory
    statement: str
    related_character_ids: tuple[str, ...] = Field(default_factory=tuple)
    related_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)


class ScheduleEntry(FrozenModel):
    start_minute: int = Field(ge=0)
    end_minute: int = Field(gt=0)
    room_id: str
    activity: str
    witnessed_by: tuple[str, ...] = Field(default_factory=tuple)


class CharacterObservation(FrozenModel):
    id: str
    minute: int = Field(ge=0)
    room_id: str
    summary: str
    fact_ids: tuple[str, ...]
    certainty: float = Field(default=1.0, ge=0.0, le=1.0)


class RelationshipDefinition(FrozenModel):
    target_character_id: str
    public_summary: str
    private_summary: str
    affinity: int = Field(default=0, ge=-100, le=100)


class LieDefinition(FrozenModel):
    id: str
    topic: str
    claim: str
    contradicts_fact_ids: tuple[str, ...]
    reason: str


class CharacterCaseOverlay(FrozenModel):
    character_id: str
    role: CharacterRole
    starting_room_id: str
    public_relationship_to_victim: str
    private_motive: str
    secrets: tuple[str, ...]
    schedule: tuple[ScheduleEntry, ...]
    observations: tuple[CharacterObservation, ...]
    alibi_claim: str
    alibi_type: AlibiType
    supporting_evidence_ids: tuple[str, ...]
    goals: tuple[str, ...]
    hides_fact_ids: tuple[str, ...]
    lies: tuple[LieDefinition, ...] = Field(default_factory=tuple)
    relationships: tuple[RelationshipDefinition, ...] = Field(default_factory=tuple)
    initial_emotional_state: str
    initial_suspicions: dict[str, int] = Field(default_factory=dict)


class CanonicalTimelineEvent(FrozenModel):
    id: str
    minute: int = Field(ge=0)
    event_type: TimelineEventType
    room_id: str
    actor_ids: tuple[str, ...]
    summary: str
    fact_ids: tuple[str, ...]
    observed_by: tuple[str, ...] = Field(default_factory=tuple)


class EvidenceDefinition(FrozenModel):
    id: str
    name: str
    kind: EvidenceKind
    description: str
    initial_slot_id: str | None = None
    fact_ids: tuple[str, ...]
    implicates_character_ids: tuple[str, ...] = Field(default_factory=tuple)
    exonerates_character_ids: tuple[str, ...] = Field(default_factory=tuple)
    is_red_herring: bool = False
    red_herring_explanation: str = ""
    discoverable_via: tuple[str, ...]
    difficulty: SearchDifficulty = SearchDifficulty.CAREFUL
    manipulable: bool = False
    essential: bool = False
    redundancy_group: str
    prerequisite_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)


class MurderTruth(FrozenModel):
    victim_id: str
    murderer_id: str
    method: str
    means: str
    weapon_id: str
    motive: str
    minute: int = Field(ge=0)
    room_id: str
    opportunity: str
    cover_story: str


class DiscoveryOpening(FrozenModel):
    discoverer_id: str
    discovery_minute: int = Field(ge=0)
    body_room_id: str
    assembly_room_id: str
    body_condition: str
    discoverer_observations: tuple[str, ...]
    containment_statement: str
    initial_reactions: dict[str, str]
    post_meeting_room_ids: dict[str, str]


class SolutionRequirements(FrozenModel):
    culprit_id: str
    method_evidence_ids: tuple[str, ...]
    motive_evidence_ids: tuple[str, ...]
    opportunity_evidence_ids: tuple[str, ...]
    timeline_fact_ids: tuple[str, ...]
    independent_evidence_groups_required: int = Field(default=3, ge=1)


class CaseDefinition(FrozenModel):
    """Immutable ground truth for one validated mystery."""

    schema_version: Literal[1] = 1
    id: str
    title: str
    seed: int
    location_package_id: str
    investigation_start_minute: int = Field(ge=0)
    turn_minutes: int = Field(default=10, ge=1, le=60)
    max_turns: int = Field(default=36, ge=1, le=200)
    initial_player_room_id: str
    character_ids: tuple[str, ...]
    murder: MurderTruth
    facts: dict[str, FactDefinition]
    timeline: tuple[CanonicalTimelineEvent, ...]
    overlays: dict[str, CharacterCaseOverlay]
    evidence: dict[str, EvidenceDefinition]
    opening: DiscoveryOpening
    solution: SolutionRequirements

    @field_validator("character_ids")
    @classmethod
    def validate_cast_size(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != 8 or len(set(value)) != 8:
            raise ValueError("a case must contain exactly eight unique NPC character IDs")
        return value


# ── Mutable runtime and knowledge layers ────────────────────────────────────


class BeliefState(StrictModel):
    subject_character_id: str
    suspicion: int = Field(default=0, ge=0, le=100)
    reason_fact_ids: list[str] = Field(default_factory=list, max_length=MAX_ACTION_ID_REFERENCES)
    summary: str = Field(default="", max_length=240)


class ConversationMemoryEntry(StrictModel):
    turn: int = Field(ge=0)
    speaker_id: str
    listener_ids: list[str] = Field(max_length=8)
    topic: str = Field(max_length=80)
    text: str = Field(max_length=MAX_ACTION_CLAIM_LENGTH)
    referenced_fact_ids: list[str] = Field(default_factory=list, max_length=MAX_ACTION_ID_REFERENCES)


class CharacterRuntimeState(StrictModel):
    character_id: str
    alive: bool = True
    current_room_id: str
    current_activity: str = "waiting"
    emotional_state: str = "guarded"
    beliefs: dict[str, BeliefState] = Field(default_factory=dict, max_length=8)
    known_fact_ids: set[str] = Field(default_factory=set)
    statement_ids_heard: set[str] = Field(default_factory=set)
    known_evidence_ids: set[str] = Field(default_factory=set)
    inventory_item_ids: list[str] = Field(default_factory=list)
    intentions: list[str] = Field(default_factory=list)
    conversation_memory: list[ConversationMemoryEntry] = Field(
        default_factory=list,
        max_length=MAX_CONVERSATION_MEMORIES,
    )


class EvidenceRuntimeState(StrictModel):
    evidence_id: str
    condition: EvidenceCondition = EvidenceCondition.IN_PLACE
    current_slot_id: str | None = None
    holder_character_id: str | None = None
    discovered_by_character_ids: set[str] = Field(default_factory=set)
    discovered_by_player: bool = False
    discovered_turn: int | None = None


class DoorRuntimeState(StrictModel):
    door_id: str
    locked: bool = False


class SearchableObjectRuntimeState(StrictModel):
    object_id: str
    search_count: int = Field(default=0, ge=0)
    fully_searched: bool = False


class ItemRuntimeState(StrictModel):
    item_id: str
    current_slot_id: str | None = None
    holder_character_id: str | None = None
    discovered_by_player: bool = False


class WeaponRuntimeState(StrictModel):
    weapon_id: str
    current_room_id: str
    holder_character_id: str | None = None
    missing_from_display: bool = False


class StatementRecord(StrictModel):
    id: str
    turn: int = Field(ge=0)
    minute: int = Field(ge=0)
    speaker_id: str
    audience_ids: list[str] = Field(max_length=8)
    topic: str = Field(max_length=80)
    claim: str = Field(max_length=MAX_ACTION_CLAIM_LENGTH)
    referenced_fact_ids: list[str] = Field(default_factory=list, max_length=MAX_ACTION_ID_REFERENCES)
    source: str = "dialogue"


class PlayerTimelineEntry(StrictModel):
    id: str
    minute: int | None = Field(default=None, ge=0)
    text: str = Field(max_length=1_000)
    source_ids: list[str] = Field(default_factory=list, max_length=MAX_ACTION_ID_REFERENCES)
    player_note: str = Field(default="", max_length=1_000)


class ContradictionRecord(StrictModel):
    id: str
    left_statement_id: str
    right_statement_id: str
    note: str = Field(default="", max_length=1_000)
    confirmed: bool = False


class PlayerKnowledgeState(StrictModel):
    discovered_room_ids: set[str] = Field(default_factory=set)
    observed_character_room_ids: dict[str, str] = Field(default_factory=dict)
    known_fact_ids: set[str] = Field(default_factory=set)
    discovered_evidence_ids: set[str] = Field(default_factory=set)
    statements: list[StatementRecord] = Field(default_factory=list, max_length=MAX_NOTEBOOK_RECORDS)
    timeline: list[PlayerTimelineEntry] = Field(default_factory=list, max_length=MAX_NOTEBOOK_RECORDS)
    contradictions: list[ContradictionRecord] = Field(default_factory=list, max_length=MAX_NOTEBOOK_RECORDS)
    notes: list[BoundedNote] = Field(default_factory=list, max_length=MAX_NOTEBOOK_RECORDS)
    unread_item_ids: set[str] = Field(default_factory=set)


class RuntimeEvent(StrictModel):
    id: str
    turn: int = Field(ge=0)
    minute: int = Field(ge=0)
    event_type: str
    room_id: str
    actor_ids: list[str]
    narration: str
    visible_to_character_ids: list[str] = Field(default_factory=list)
    visible_to_player: bool = False
    fact_ids: list[str] = Field(default_factory=list)


class InterviewSession(StrictModel):
    character_id: str
    started_turn: int
    exchanges_used: int = Field(default=0, ge=0, le=3)
    max_exchanges: int = Field(default=3, ge=1, le=10)
    statement_ids: list[str] = Field(default_factory=list)


class GameResult(StrictModel):
    accused_character_id: str
    correct_culprit: bool
    support_score: int = Field(ge=0, le=3)
    submitted_method: str = Field(max_length=MAX_ACTION_CLAIM_LENGTH)
    submitted_motive: str = Field(max_length=MAX_ACTION_CLAIM_LENGTH)
    submitted_timeline: str = Field(max_length=MAX_ACTION_CLAIM_LENGTH)
    method_supported: bool = False
    motive_supported: bool = False
    timeline_supported: bool = False
    solved: bool
    selected_evidence_ids: list[str] = Field(max_length=MAX_ACTION_ID_REFERENCES)
    selected_timeline_fact_ids: list[str] = Field(max_length=MAX_ACTION_ID_REFERENCES)
    summary: str = Field(max_length=500)


class ActionHistoryEntry(StrictModel):
    """One accepted state-changing command plus its bounded NPC selections."""

    intent: dict[str, Any] = Field(max_length=16)
    npc_action_ids: dict[BoundedIdentifier, BoundedIdentifier] | None = Field(
        default=None,
        max_length=8,
    )


class WorldRuntimeState(StrictModel):
    """Mutable present world, deliberately excluding immutable case truth."""

    schema_version: Literal[1] = 1
    case_id: str
    seed: int
    phase: GamePhase = GamePhase.DISCOVERY
    turn: int = Field(default=0, ge=0)
    in_game_minute: int = Field(ge=0)
    player_room_id: str
    characters: dict[str, CharacterRuntimeState]
    evidence: dict[str, EvidenceRuntimeState]
    doors: dict[str, DoorRuntimeState] = Field(default_factory=dict)
    searchable_objects: dict[str, SearchableObjectRuntimeState] = Field(
        default_factory=dict
    )
    items: dict[str, ItemRuntimeState] = Field(default_factory=dict)
    weapons: dict[str, WeaponRuntimeState] = Field(default_factory=dict)
    player_knowledge: PlayerKnowledgeState = Field(default_factory=PlayerKnowledgeState)
    event_log: list[RuntimeEvent] = Field(default_factory=list)
    active_interview: InterviewSession | None = None
    result: GameResult | None = None
