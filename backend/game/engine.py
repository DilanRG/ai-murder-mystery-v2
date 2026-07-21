"""Deterministic authoritative turn engine for the Ashwick vertical slice."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Mapping

from game.actions import (
    AccuseIntent,
    AddNoteIntent,
    AddTimelineEntryIntent,
    AdvanceOpeningIntent,
    BeginInterviewIntent,
    EndInterviewIntent,
    ExamineBodyIntent,
    ExamineEvidenceIntent,
    ExamineSceneIntent,
    InterviewExchangeIntent,
    MoveIntent,
    MarkContradictionIntent,
    PlayerIntent,
    ReviewNotebookIntent,
    SearchIntent,
    parse_player_intent,
)
from game.content import load_character_card
from game.accusation import evaluate_accusation_support
from game.models import (
    ActionHistoryEntry,
    BeliefState,
    CaseDefinition,
    CharacterRuntimeState,
    ConversationMemoryEntry,
    ContradictionRecord,
    DoorRuntimeState,
    EvidenceCondition,
    EvidenceRuntimeState,
    GamePhase,
    GameResult,
    ItemRuntimeState,
    MAX_ACTION_CLAIM_LENGTH,
    LocationPackage,
    MAX_CONVERSATION_MEMORIES,
    MAX_NOTEBOOK_RECORDS,
    SearchableObjectRuntimeState,
    StatementRecord,
    PlayerTimelineEntry,
    WeaponRuntimeState,
    WorldRuntimeState,
)
from game.npc_planning import (
    MAX_CANDIDATES_PER_ACTOR,
    NpcActionCandidate,
    NpcActorActionOptions,
    NpcIntentPlanningRequest,
    SafeNpcTurnSnapshot,
)
from game.private_npc_agents import (
    PrivateNpcAgentRequest,
    PrivateNpcBriefing,
    PrivateNpcFact,
    PrivateNpcRuntimeState,
)
from game.private_interview import (
    InterviewResponseKind,
    PrivateInterviewResponseCandidate,
    PrivateInterviewResponseRequest,
)
from game.validator import validate_case
from game.public_assets import portrait_url
from game.recipes import CaseRecipeSelection
from game.story_director import (
    StoryPresentationPatch,
    fallback_story_presentation,
    validate_story_presentation,
)
from game.views import (
    PlayerGameView,
    PublicCharacterView,
    PublicEvidenceView,
    PublicFactView,
    PublicItemView,
    PublicContradictionView,
    PublicOpeningView,
    PublicResultView,
    PublicRoomView,
    PublicSceneActionView,
    PublicStatementView,
    PublicStoryPresentationView,
    PublicTimelineEntryView,
    TurnResultView,
)


PLAYER_ID = "player"
_GENERATED_MURDERER_ALIBI = (
    "I was occupied elsewhere during the relevant period and had no part in the death."
)
_GENERATED_MURDERER_LIES = (
    "I have no involvement in the death.",
    "Nothing I have withheld would explain what happened.",
    "You are looking in the wrong direction.",
)


@dataclass(frozen=True)
class _NpcIntent:
    """A turn-start NPC decision; resolution happens later in initiative order."""

    character_id: str
    destination_room_id: str | None
    manipulate_evidence_id: str | None
    social: _NpcSocialIntent | None = None


@dataclass(frozen=True)
class _NpcSocialIntent:
    """An engine-authored private claim or reaction to one co-located NPC."""

    target_character_id: str
    topic: str
    claim: str
    referenced_fact_ids: tuple[str, ...] = ()
    transfers_facts: bool = False


@dataclass(frozen=True)
class EngineActionPreview:
    """Result of applying a command to a deep-copied runtime only."""

    result: TurnResultView
    npc_request: NpcIntentPlanningRequest | None
    private_npc_requests: tuple[PrivateNpcAgentRequest, ...] | None
    private_interview_request: PrivateInterviewResponseRequest | None


class GameEngine:
    """Owns mutable runtime state while retaining immutable authored truth."""

    def __init__(
        self,
        case: CaseDefinition,
        location: LocationPackage,
        *,
        recipe_selection: CaseRecipeSelection | None = None,
        story_presentation: StoryPresentationPatch | None = None,
    ) -> None:
        report = validate_case(case, location)
        if not report.valid:
            raise ValueError(f"cannot start invalid case: {report.issues!r}")
        self.case = case
        self.location = location
        self.recipe_selection = recipe_selection
        self.story_presentation = (
            fallback_story_presentation(case, location)
            if story_presentation is None
            else validate_story_presentation(story_presentation, case, location)
        )
        self.action_history: list[ActionHistoryEntry] | None = []
        self.runtime = self._initial_runtime()

    @classmethod
    def create(
        cls,
        case: CaseDefinition,
        location: LocationPackage,
        *,
        recipe_selection: CaseRecipeSelection | None = None,
        story_presentation: StoryPresentationPatch | None = None,
    ) -> "GameEngine":
        return cls(
            case,
            location,
            recipe_selection=recipe_selection,
            story_presentation=story_presentation,
        )

    def _initial_runtime(self) -> WorldRuntimeState:
        characters = {
            character_id: CharacterRuntimeState(
                character_id=character_id,
                alive=character_id != self.case.murder.victim_id,
                current_room_id=(
                    self.case.opening.body_room_id
                    if character_id == self.case.murder.victim_id
                    else self.case.opening.assembly_room_id
                ),
                current_activity=("dead" if character_id == self.case.murder.victim_id else "at the opening meeting"),
                emotional_state=self.case.overlays[character_id].initial_emotional_state,
                beliefs=(
                    {
                        subject_id: BeliefState(
                            subject_character_id=subject_id,
                            suspicion=suspicion,
                            summary="Authored initial suspicion.",
                        )
                        for subject_id, suspicion in self.case.overlays[
                            character_id
                        ].initial_suspicions.items()
                    }
                    if character_id != self.case.murder.victim_id
                    else {}
                ),
                # Related-character links are validation metadata, not a grant
                # of omniscience.  Runtime knowledge starts only with authored
                # observations and facts the overlay explicitly says this NPC
                # is concealing (private knowledge, not a player-facing leak).
                known_fact_ids=(
                    {
                        fact_id
                        for observation in self.case.overlays[character_id].observations
                        for fact_id in observation.fact_ids
                    }
                    | set(self.case.overlays[character_id].hides_fact_ids)
                ),
                known_evidence_ids=set(self.case.overlays[character_id].supporting_evidence_ids),
            )
            for character_id in self.case.character_ids
        }
        evidence = {
            evidence_id: EvidenceRuntimeState(
                evidence_id=evidence_id,
                current_slot_id=definition.initial_slot_id,
            )
            for evidence_id, definition in self.case.evidence.items()
        }
        doors = {
            door.id: DoorRuntimeState(door_id=door.id, locked=door.locked_by_default)
            for door in self.location.doors
        }
        objects = {
            object_id: SearchableObjectRuntimeState(object_id=object_id)
            for object_id in self.location.searchable_objects
        }
        items = {
            item_id: ItemRuntimeState(item_id=item_id, current_slot_id=item.initial_slot_id)
            for item_id, item in self.location.items.items()
        }
        weapons = {
            weapon_id: WeaponRuntimeState(weapon_id=weapon_id, current_room_id=weapon.room_id)
            for weapon_id, weapon in self.location.potential_weapons.items()
        }
        return WorldRuntimeState(
            case_id=self.case.id,
            seed=self.case.seed,
            phase=GamePhase.DISCOVERY,
            in_game_minute=self.case.investigation_start_minute,
            player_room_id=self.case.opening.assembly_room_id,
            characters=characters,
            evidence=evidence,
            doors=doors,
            searchable_objects=objects,
            items=items,
            weapons=weapons,
        )

    def view(self) -> PlayerGameView:
        room = self.location.rooms[self.runtime.player_room_id]
        exits = sorted(self._unlocked_destinations(room.id))
        present = [
            self._character_view(character_id, expose_emotion=True)
            for character_id in sorted(self.runtime.characters)
            if self.runtime.characters[character_id].alive
            and self.runtime.characters[character_id].current_room_id == room.id
        ]
        evidence = [
            self._evidence_view(evidence_id)
            for evidence_id in sorted(self.runtime.player_knowledge.discovered_evidence_ids)
        ]
        known_facts = [
            self._fact_view(fact_id)
            for fact_id in sorted(self.runtime.player_knowledge.known_fact_ids)
            if fact_id in self.case.facts
        ]
        inventory = [
            self._item_view(item_id)
            for item_id, state in sorted(self.runtime.items.items())
            if state.discovered_by_player and state.holder_character_id == PLAYER_ID
        ]
        interview = self.runtime.active_interview
        return PlayerGameView(
            case_title=self.story_presentation.title,
            story=PublicStoryPresentationView(
                source=self.story_presentation.source,
                tagline=self.story_presentation.tagline,
                public_opening=self.story_presentation.public_opening,
                atmosphere=self.story_presentation.atmosphere,
                character_tensions={
                    item.character_id: item.public_hook
                    for item in self.story_presentation.character_tensions
                },
                room_flavour={
                    item.room_id: item.text
                    for item in self.story_presentation.room_flavour
                },
            ),
            phase=self.runtime.phase.value,
            turn=self.runtime.turn,
            in_game_minute=self.runtime.in_game_minute,
            time_label=self._time_label(self.runtime.in_game_minute),
            player_room=PublicRoomView(
                id=room.id,
                name=room.name,
                description=next(
                    (
                        item.text
                        for item in self.story_presentation.room_flavour
                        if item.room_id == room.id
                    ),
                    room.description,
                ),
                exits=exits,
                searchable_objects=[
                    {"id": object_id, "name": self.location.searchable_objects[object_id].name}
                    for object_id in room.searchable_object_ids
                ],
            ),
            present_characters=present,
            suspects=[
                self._character_view(character_id)
                for character_id in sorted(self.runtime.characters)
                if self.runtime.characters[character_id].alive
            ],
            discovered_evidence=evidence,
            known_facts=known_facts,
            inventory=inventory,
            available_scenes=(
                [
                    PublicSceneActionView(
                        id="body",
                        label="Examine the body",
                        description="The preserved body scene remains available for examination.",
                    )
                ]
                if self.runtime.phase == GamePhase.INVESTIGATION
                and room.id == self.case.opening.body_room_id
                else []
            ),
            statements=[self._statement_view(statement) for statement in self.runtime.player_knowledge.statements],
            timeline=[
                PublicTimelineEntryView(
                    id=entry.id,
                    minute=entry.minute,
                    text=entry.text,
                    source_ids=list(entry.source_ids),
                    player_note=entry.player_note,
                )
                for entry in self.runtime.player_knowledge.timeline
            ],
            contradictions=[
                PublicContradictionView(
                    id=entry.id,
                    left_statement_id=entry.left_statement_id,
                    right_statement_id=entry.right_statement_id,
                    note=entry.note,
                    confirmed=entry.confirmed,
                )
                for entry in self.runtime.player_knowledge.contradictions
            ],
            notes=list(self.runtime.player_knowledge.notes),
            opening=self._opening_view() if self.runtime.phase == GamePhase.DISCOVERY else None,
            active_interview_character_id=interview.character_id if interview else None,
            active_interview_exchanges_remaining=(interview.max_exchanges - interview.exchanges_used if interview else None),
            result=self._result_view(),
        )

    player_view = view

    def apply(
        self,
        intent: PlayerIntent | dict[str, object],
        *,
        npc_action_ids: Mapping[str, str] | None = None,
        interview_response_id: str | None = None,
        interview_rules_version: int | None = None,
    ) -> TurnResultView:
        """Apply an intent synchronously, retaining deterministic NPC fallback.

        ``npc_action_ids`` may contain only IDs from a request produced by this
        engine.  The NPC phase rebuilds and validates the finite candidate set
        before resolving them; absent or stale IDs fall back deterministically.
        """

        command = parse_player_intent(intent) if isinstance(intent, dict) else intent
        if interview_rules_version not in {None, 1, 2}:
            raise ValueError("interview_rules_version must be 1 or 2")
        if not isinstance(command, InterviewExchangeIntent):
            if interview_response_id is not None:
                raise ValueError(
                    "interview_response_id is valid only for interview exchanges"
                )
            if interview_rules_version is not None:
                raise ValueError(
                    "interview_rules_version is valid only for interview exchanges"
                )
            resolved_interview_rules_version = None
        else:
            resolved_interview_rules_version = interview_rules_version or 2
            if (
                resolved_interview_rules_version == 1
                and interview_response_id is not None
            ):
                raise ValueError(
                    "legacy interview rules cannot contain a response ID"
                )
        result = self._apply(
            command,
            npc_action_ids=npc_action_ids,
            interview_response_id=interview_response_id,
            interview_rules_version=resolved_interview_rules_version,
            defer_npc_phase=False,
        )
        if (
            result.accepted
            and not isinstance(command, ReviewNotebookIntent)
            and self.action_history is not None
        ):
            self.action_history.append(
                ActionHistoryEntry(
                    intent=command.model_dump(mode="json"),
                    npc_action_ids=(
                        dict(npc_action_ids) if npc_action_ids is not None else None
                    ),
                    interview_response_id=interview_response_id,
                    interview_rules_version=resolved_interview_rules_version,
                )
            )
        return result

    def preview(self, intent: PlayerIntent | dict[str, object]) -> EngineActionPreview:
        """Preview against a deep copy and capture the post-player NPC request.

        Provider latency and cancellation therefore happen before the original
        runtime is touched.  Canonical case/location models are frozen and may
        be shared; every mutable runtime model is copied recursively.
        """

        command = parse_player_intent(intent) if isinstance(intent, dict) else intent
        clone = object.__new__(GameEngine)
        clone.case = self.case
        clone.location = self.location
        clone.recipe_selection = self.recipe_selection
        clone.story_presentation = self.story_presentation
        clone.action_history = (
            [entry.model_copy(deep=True) for entry in self.action_history]
            if self.action_history is not None
            else None
        )
        clone.runtime = self.runtime.model_copy(deep=True)
        private_interview_request = (
            clone._build_private_interview_request(command)
            if isinstance(command, InterviewExchangeIntent)
            else None
        )
        result = clone._apply(
            command,
            npc_action_ids=None,
            interview_response_id=None,
            interview_rules_version=(
                2 if isinstance(command, InterviewExchangeIntent) else None
            ),
            defer_npc_phase=True,
        )
        if not result.accepted:
            private_interview_request = None
        request = clone._build_npc_planning_request() if result.accepted and result.committed else None
        private_requests = (
            clone._build_private_npc_requests(request)
            if request is not None
            else None
        )
        return EngineActionPreview(
            result=result,
            npc_request=request,
            private_npc_requests=private_requests,
            private_interview_request=private_interview_request,
        )

    def _apply(
        self,
        intent: PlayerIntent | dict[str, object],
        *,
        npc_action_ids: Mapping[str, str] | None,
        interview_response_id: str | None,
        interview_rules_version: int | None,
        defer_npc_phase: bool,
    ) -> TurnResultView:
        command = parse_player_intent(intent) if isinstance(intent, dict) else intent
        if self.runtime.phase == GamePhase.ENDED:
            return self._reject("The case has already ended.")
        if isinstance(command, AdvanceOpeningIntent):
            return self._advance_opening()
        if self.runtime.phase != GamePhase.INVESTIGATION:
            return self._reject("The opening meeting must conclude before investigating.")
        if isinstance(command, MoveIntent):
            return self._move(command, npc_action_ids, defer_npc_phase)
        if isinstance(command, SearchIntent):
            return self._search(command, npc_action_ids, defer_npc_phase)
        if isinstance(command, BeginInterviewIntent):
            return self._begin_interview(command)
        if isinstance(command, InterviewExchangeIntent):
            assert interview_rules_version is not None
            return self._interview_exchange(
                command,
                interview_response_id,
                interview_rules_version,
            )
        if isinstance(command, EndInterviewIntent):
            return self._end_interview(npc_action_ids, defer_npc_phase)
        if isinstance(command, ExamineEvidenceIntent):
            return self._examine(command, npc_action_ids, defer_npc_phase)
        if isinstance(command, (ExamineSceneIntent, ExamineBodyIntent)):
            return self._examine_body(command, npc_action_ids, defer_npc_phase)
        if isinstance(command, ReviewNotebookIntent):
            return self._accept(False, "You review the notes without spending investigation time.")
        if isinstance(command, AddNoteIntent):
            if len(self.runtime.player_knowledge.notes) >= MAX_NOTEBOOK_RECORDS:
                return self._reject("The notebook note limit has been reached.")
            self.runtime.player_knowledge.notes.append(command.text)
            return self._accept(False, "You add a note to the notebook.")
        if isinstance(command, AddTimelineEntryIntent):
            return self._add_timeline_entry(command)
        if isinstance(command, MarkContradictionIntent):
            return self._mark_contradiction(command)
        if isinstance(command, AccuseIntent):
            return self._accuse(command, npc_action_ids, defer_npc_phase)
        return self._reject("Unsupported player intent.")

    apply_intent = apply

    def begin_investigation(self) -> TurnResultView:
        """Convenience entry point for a UI button completing the opening."""
        return self.apply(AdvanceOpeningIntent())

    def _advance_opening(self) -> TurnResultView:
        if self.runtime.phase != GamePhase.DISCOVERY:
            return self._reject("The opening meeting has already concluded.")
        self.runtime.phase = GamePhase.INVESTIGATION
        self.runtime.player_room_id = self.case.initial_player_room_id
        for character_id, room_id in self.case.opening.post_meeting_room_ids.items():
            character = self.runtime.characters[character_id]
            character.current_room_id = room_id
            character.current_activity = "dispersed"
        self.runtime.player_knowledge.discovered_room_ids.add(self.runtime.player_room_id)
        return self._accept(False, "The meeting breaks. The investigation begins.")

    def _move(
        self,
        intent: MoveIntent,
        npc_action_ids: Mapping[str, str] | None,
        defer_npc_phase: bool,
    ) -> TurnResultView:
        if self.runtime.active_interview:
            return self._reject("End the current interview before moving.")
        door = self._door_between(self.runtime.player_room_id, intent.room_id)
        if door is None:
            return self._reject("That room is not connected by a valid route.")
        if self.runtime.doors[door.id].locked:
            return self._reject("That route is locked.")
        self.runtime.player_room_id = intent.room_id
        self.runtime.player_knowledge.discovered_room_ids.add(intent.room_id)
        return self._commit(
            f"You move to {self.location.rooms[intent.room_id].name}.",
            npc_action_ids=npc_action_ids,
            defer_npc_phase=defer_npc_phase,
        )

    def _search(
        self,
        intent: SearchIntent,
        npc_action_ids: Mapping[str, str] | None,
        defer_npc_phase: bool,
    ) -> TurnResultView:
        if self.runtime.active_interview:
            return self._reject("End the current interview before searching.")
        obj = self.location.searchable_objects.get(intent.object_id)
        if obj is None or obj.room_id != self.runtime.player_room_id:
            return self._reject("That object is not available in this room.")
        if obj.requires_item_id and not self._player_has_item(obj.requires_item_id):
            return self._reject("You lack the item needed to search that object.")
        state = self.runtime.searchable_objects[intent.object_id]
        state.search_count += 1
        discoveries: list[PublicEvidenceView] = []
        found_items: list[PublicItemView] = []
        route = f"search:{intent.object_id}"
        for evidence_id, definition in self.case.evidence.items():
            if route not in definition.discoverable_via or definition.difficulty.value > state.search_count:
                continue
            evidence_state = self.runtime.evidence[evidence_id]
            if definition.initial_slot_id is not None:
                current_slot = (
                    self.location.evidence_slots.get(evidence_state.current_slot_id)
                    if evidence_state.current_slot_id is not None
                    else None
                )
                if current_slot is None or current_slot.object_id != intent.object_id:
                    continue
            found = self._discover_evidence(evidence_id)
            if found:
                discoveries.append(self._evidence_view(evidence_id))
        for item_id, item in self.location.items.items():
            if item.initial_slot_id in obj.evidence_slot_ids and not self.runtime.items[item_id].discovered_by_player:
                self.runtime.items[item_id].discovered_by_player = True
                self.runtime.items[item_id].holder_character_id = PLAYER_ID
                self.runtime.items[item_id].current_slot_id = None
                found_items.append(self._item_view(item_id))
        threshold = max([obj.difficulty.value] + [
            definition.difficulty.value
            for definition in self.case.evidence.values()
            if route in definition.discoverable_via
        ])
        state.fully_searched = state.search_count >= threshold
        found_names = [item.name for item in discoveries] + [item.name for item in found_items]
        suffix = " You find " + ", ".join(found_names) + "." if found_names else " Nothing new turns up."
        return self._commit(
            obj.search_text + suffix,
            discoveries=discoveries,
            items=found_items,
            npc_action_ids=npc_action_ids,
            defer_npc_phase=defer_npc_phase,
        )

    def _begin_interview(self, intent: BeginInterviewIntent) -> TurnResultView:
        if self.runtime.active_interview:
            return self._reject("An interview is already in progress.")
        character = self.runtime.characters.get(intent.character_id)
        if character is None or not character.alive:
            return self._reject("That character cannot be interviewed.")
        if character.current_room_id != self.runtime.player_room_id:
            return self._reject("That character is not in this room.")
        from game.models import InterviewSession

        self.runtime.active_interview = InterviewSession(character_id=intent.character_id, started_turn=self.runtime.turn)
        return self._accept(False, f"You begin speaking with {self._name(intent.character_id)}.")

    def _build_private_interview_request(
        self,
        intent: InterviewExchangeIntent,
    ) -> PrivateInterviewResponseRequest | None:
        """Build one target-only selector request without mutating the runtime."""

        session = self.runtime.active_interview
        if (
            session is None
            or session.exchanges_used >= session.max_exchanges
            or len(self.runtime.player_knowledge.statements) >= MAX_NOTEBOOK_RECORDS
        ):
            return None
        character = self.runtime.characters.get(session.character_id)
        if (
            character is None
            or not character.alive
            or character.current_room_id != self.runtime.player_room_id
        ):
            return None
        candidates = self._interview_response_candidates(
            session.character_id,
            player_question=intent.message,
            exchange_index=session.exchanges_used,
            started_turn=session.started_turn,
        )
        fallback = self._deterministic_interview_fallback(
            candidates,
            session.exchanges_used,
        )
        public_request = self._build_npc_planning_request()
        private_context = next(
            request
            for request in self._build_private_npc_requests(public_request)
            if request.actor_id == session.character_id
        )
        facts = list(private_context.private_briefing.private_facts)
        while True:
            try:
                return PrivateInterviewResponseRequest(
                    actor_id=session.character_id,
                    player_question=intent.message,
                    private_briefing=PrivateNpcBriefing(
                        character_summary=(
                            private_context.private_briefing.character_summary
                        ),
                        private_facts=tuple(facts),
                    ),
                    runtime_state=private_context.runtime_state,
                    fallback_response_id=fallback.response_id,
                    candidates=candidates,
                )
            except ValueError:
                if not facts:
                    raise
                # Facts are already priority ordered, so discard from the end
                # until the interview-specific candidate set fits its budget.
                facts.pop()

    def _interview_response_candidates(
        self,
        character_id: str,
        *,
        player_question: str,
        exchange_index: int,
        started_turn: int,
    ) -> tuple[PrivateInterviewResponseCandidate, ...]:
        """Return finite target-owned responses; never synthesize case truth."""

        overlay = self.case.overlays[character_id]
        known_fact_ids = self.runtime.characters[character_id].known_fact_ids
        hidden_fact_ids = set(overlay.hides_fact_ids)
        candidates: list[PrivateInterviewResponseCandidate] = []

        def add(
            kind: InterviewResponseKind,
            claim: str,
            fact_ids: tuple[str, ...] = (),
        ) -> None:
            bounded_claim = claim[:1_200]
            if not bounded_claim:
                return
            material = "\x1f".join(
                (
                    character_id,
                    str(started_turn),
                    str(exchange_index),
                    player_question,
                    kind.value,
                    bounded_claim,
                    ",".join(fact_ids),
                )
            ).encode("utf-8")
            candidates.append(
                PrivateInterviewResponseCandidate(
                    response_id=(
                        f"reply_{hashlib.sha256(material).hexdigest()[:24]}"
                    ),
                    kind=kind,
                    canonical_claim=bounded_claim,
                    referenced_fact_ids=fact_ids,
                )
            )

        add(
            InterviewResponseKind.EVASIVE,
            "I am not prepared to say more about that yet.",
        )
        for observation in sorted(overlay.observations, key=lambda item: item.id):
            observation_facts = set(observation.fact_ids)
            if (
                observation_facts
                and observation_facts <= known_fact_ids
                and not observation_facts & hidden_fact_ids
            ):
                add(
                    InterviewResponseKind.TRUTHFUL_OBSERVATION,
                    observation.summary,
                    observation.fact_ids,
                )
        untrusted_murderer_claims = (
            self.case.id.startswith("generated_")
            and character_id == self.case.murder.murderer_id
        )
        if untrusted_murderer_claims:
            # Generated prose cannot prove its own disclosure manifest. Keep
            # the murderer deceptive without ever exposing provider-authored
            # alibi/lie text at the player-facing selector boundary.
            add(InterviewResponseKind.ALIBI, _GENERATED_MURDERER_ALIBI)
            for index, _lie in enumerate(
                sorted(overlay.lies, key=lambda item: item.id)
            ):
                add(
                    InterviewResponseKind.AUTHORIZED_LIE,
                    _GENERATED_MURDERER_LIES[
                        index % len(_GENERATED_MURDERER_LIES)
                    ],
                )
        elif not set(overlay.alibi_disclosed_fact_ids) & hidden_fact_ids:
            add(InterviewResponseKind.ALIBI, overlay.alibi_claim)
        if not untrusted_murderer_claims:
            for lie in sorted(overlay.lies, key=lambda item: item.id):
                if not set(lie.disclosed_fact_ids) & hidden_fact_ids:
                    add(InterviewResponseKind.AUTHORIZED_LIE, lie.claim)
        return tuple(candidates[:8])

    @staticmethod
    def _deterministic_interview_fallback(
        candidates: tuple[PrivateInterviewResponseCandidate, ...],
        exchange_index: int,
    ) -> PrivateInterviewResponseCandidate:
        """Choose useful authored material when the private selector is unavailable."""

        useful = tuple(
            candidate
            for kind in (
                InterviewResponseKind.ALIBI,
                InterviewResponseKind.TRUTHFUL_OBSERVATION,
                InterviewResponseKind.AUTHORIZED_LIE,
            )
            for candidate in candidates
            if candidate.kind == kind
        )
        return useful[exchange_index % len(useful)] if useful else candidates[0]

    def _interview_exchange(
        self,
        intent: InterviewExchangeIntent,
        interview_response_id: str | None,
        interview_rules_version: int,
    ) -> TurnResultView:
        session = self.runtime.active_interview
        if session is None:
            return self._reject("Begin an interview before asking a question.")
        if session.exchanges_used >= session.max_exchanges:
            return self._reject("This interview has reached its three-exchange limit; end it to continue.")
        character = self.runtime.characters[session.character_id]
        if not character.alive or character.current_room_id != self.runtime.player_room_id:
            self.runtime.active_interview = None
            return self._reject("The interview is no longer possible in this room.")
        overlay = self.case.overlays[session.character_id]
        if len(self.runtime.player_knowledge.statements) >= MAX_NOTEBOOK_RECORDS:
            return self._reject("The interview record limit has been reached.")
        index = session.exchanges_used
        if interview_rules_version == 1:
            # Exact pre-private-agent behavior for schema-v2 save replay. It
            # intentionally does not grant referenced facts to the player.
            legacy_choices = [
                (overlay.alibi_claim, list()),
                *[
                    (observation.summary, list(observation.fact_ids))
                    for observation in overlay.observations
                ],
                *[(lie.claim, list()) for lie in overlay.lies],
            ]
            text, referenced_fact_ids = (
                legacy_choices[index % len(legacy_choices)]
                if legacy_choices
                else ("I have nothing useful to add.", [])
            )
            statement_source = "deterministic_fallback"
        else:
            candidates = self._interview_response_candidates(
                session.character_id,
                player_question=intent.message,
                exchange_index=session.exchanges_used,
                started_turn=session.started_turn,
            )
            if interview_response_id is None:
                selected = self._deterministic_interview_fallback(candidates, index)
                statement_source = "deterministic_fallback"
            else:
                selected = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate.response_id == interview_response_id
                    ),
                    candidates[0],
                )
                statement_source = f"private_agent_{selected.kind.value}"
            text = selected.canonical_claim
            referenced_fact_ids = list(selected.referenced_fact_ids)
        statement = StatementRecord(
            id=f"statement_{self.runtime.turn}_{session.character_id}_{index}",
            turn=self.runtime.turn,
            minute=self.runtime.in_game_minute,
            speaker_id=session.character_id,
            audience_ids=[PLAYER_ID],
            topic=(intent.message.strip()[:80] or "interview"),
            claim=text,
            referenced_fact_ids=referenced_fact_ids,
            source=statement_source,
        )
        self.runtime.player_knowledge.statements.append(statement)
        if (
            interview_rules_version == 2
            and selected.kind == InterviewResponseKind.TRUTHFUL_OBSERVATION
        ):
            self.runtime.player_knowledge.known_fact_ids.update(
                selected.referenced_fact_ids
            )
        character.conversation_memory.append(
            ConversationMemoryEntry(
                turn=statement.turn,
                speaker_id=session.character_id,
                listener_ids=[PLAYER_ID],
                topic=statement.topic,
                text=statement.claim,
                referenced_fact_ids=list(statement.referenced_fact_ids),
            )
        )
        session.statement_ids.append(statement.id)
        session.exchanges_used += 1
        discoveries: list[PublicEvidenceView] = []
        route = f"interview:{session.character_id}"
        for evidence_id, definition in self.case.evidence.items():
            if route in definition.discoverable_via and self._discover_evidence(
                evidence_id,
                required_room_id=self.runtime.player_room_id,
            ):
                discoveries.append(self._evidence_view(evidence_id))
                break  # exactly one authored interview clue per exchange
        return self._accept(
            False,
            f"{self._name(session.character_id)} answers.",
            discoveries=discoveries,
            dialogue=PublicStatementView(
                id=statement.id,
                turn=statement.turn,
                minute=statement.minute,
                speaker_id=session.character_id,
                speaker_name=self._name(session.character_id),
                text=text,
                topic=statement.topic,
            ),
        )

    def _add_timeline_entry(self, intent: AddTimelineEntryIntent) -> TurnResultView:
        if len(self.runtime.player_knowledge.timeline) >= MAX_NOTEBOOK_RECORDS:
            return self._reject("The timeline entry limit has been reached.")
        valid_sources = self._notebook_source_ids()
        if any(source_id not in valid_sources for source_id in intent.source_ids):
            return self._reject(
                "Timeline entries may cite only learned facts, discovered evidence, or recorded statements."
            )
        if intent.minute is not None and intent.minute > self.runtime.in_game_minute:
            return self._reject("A timeline entry cannot be dated later than the current investigation time.")
        entry = PlayerTimelineEntry(
            id=f"timeline_{len(self.runtime.player_knowledge.timeline) + 1}",
            minute=intent.minute,
            text=intent.text,
            source_ids=list(intent.source_ids),
        )
        self.runtime.player_knowledge.timeline.append(entry)
        return self._accept(False, "You add an entry to the timeline.")

    def _mark_contradiction(self, intent: MarkContradictionIntent) -> TurnResultView:
        if len(self.runtime.player_knowledge.contradictions) >= MAX_NOTEBOOK_RECORDS:
            return self._reject("The contradiction record limit has been reached.")
        known_statement_ids = {statement.id for statement in self.runtime.player_knowledge.statements}
        if (
            intent.left_statement_id == intent.right_statement_id
            or intent.left_statement_id not in known_statement_ids
            or intent.right_statement_id not in known_statement_ids
        ):
            return self._reject("A contradiction must reference two different recorded statements.")
        record = ContradictionRecord(
            id=f"contradiction_{len(self.runtime.player_knowledge.contradictions) + 1}",
            left_statement_id=intent.left_statement_id,
            right_statement_id=intent.right_statement_id,
            note=intent.note,
        )
        self.runtime.player_knowledge.contradictions.append(record)
        return self._accept(False, "You mark the contradiction for later review.")

    def _end_interview(
        self,
        npc_action_ids: Mapping[str, str] | None,
        defer_npc_phase: bool,
    ) -> TurnResultView:
        if self.runtime.active_interview is None:
            return self._reject("There is no interview to end.")
        name = self._name(self.runtime.active_interview.character_id)
        self.runtime.active_interview = None
        return self._commit(
            f"You conclude the interview with {name}.",
            npc_action_ids=npc_action_ids,
            defer_npc_phase=defer_npc_phase,
        )

    def _examine(
        self,
        intent: ExamineEvidenceIntent,
        npc_action_ids: Mapping[str, str] | None,
        defer_npc_phase: bool,
    ) -> TurnResultView:
        if self.runtime.active_interview:
            return self._reject("End the current interview before examining evidence.")
        if intent.evidence_id not in self.runtime.player_knowledge.discovered_evidence_ids:
            return self._reject("You have not discovered that evidence.")
        evidence = self.case.evidence[intent.evidence_id]
        return self._commit(
            f"You examine {evidence.name}: {evidence.description}",
            npc_action_ids=npc_action_ids,
            defer_npc_phase=defer_npc_phase,
        )

    def _examine_body(
        self,
        intent: ExamineSceneIntent | ExamineBodyIntent,
        npc_action_ids: Mapping[str, str] | None,
        defer_npc_phase: bool,
    ) -> TurnResultView:
        if self.runtime.active_interview:
            return self._reject("End the current interview before examining the scene.")
        scene_id = "body" if isinstance(intent, ExamineBodyIntent) else intent.scene_id
        if scene_id != "body" or self.runtime.player_room_id != self.case.opening.body_room_id:
            return self._reject("The body can only be examined at the preserved body scene.")
        discoveries: list[PublicEvidenceView] = []
        for evidence_id, definition in self.case.evidence.items():
            if "examine:body" in definition.discoverable_via and self._discover_evidence(
                evidence_id,
                required_room_id=self.runtime.player_room_id,
            ):
                discoveries.append(self._evidence_view(evidence_id))
        narration = "You examine the body and preserve the visible scene." if not discoveries else (
            "You examine the body and preserve the scene: " + ", ".join(item.name for item in discoveries) + "."
        )
        return self._commit(
            narration,
            discoveries=discoveries,
            npc_action_ids=npc_action_ids,
            defer_npc_phase=defer_npc_phase,
        )

    def _accuse(
        self,
        intent: AccuseIntent,
        npc_action_ids: Mapping[str, str] | None,
        defer_npc_phase: bool,
    ) -> TurnResultView:
        if self.runtime.active_interview:
            return self._reject("End the current interview before making an accusation.")
        if intent.character_id not in self.runtime.characters or not self.runtime.characters[intent.character_id].alive:
            return self._reject("Choose a living suspect.")
        submitted_evidence = (
            set(intent.evidence_ids)
            | set(intent.method_evidence_ids)
            | set(intent.motive_evidence_ids)
            | set(intent.opportunity_evidence_ids)
            | set(intent.timeline_evidence_ids)
        )
        selected = (
            submitted_evidence
            & self.runtime.player_knowledge.discovered_evidence_ids
        )
        solution = self.case.solution
        support_flags = evaluate_accusation_support(
            self.case,
            known_fact_ids=self.runtime.player_knowledge.known_fact_ids,
            selected_evidence_ids=selected,
            method=intent.method,
            motive=intent.motive,
            timeline=intent.timeline,
        )
        # Evidence is the authoritative support.  The explicit method, motive,
        # and timeline inputs are checked when supplied, so an evidence-backed
        # but internally inconsistent accusation cannot receive that component.
        support_score = sum(support_flags)
        correct = intent.character_id == solution.culprit_id
        solved = correct and support_score >= 2
        selected_timeline_facts = sorted(
            set(intent.timeline_fact_ids)
            & self.runtime.player_knowledge.known_fact_ids
            & set(solution.timeline_fact_ids)
        )
        self.runtime.phase = GamePhase.ENDED
        self.runtime.result = GameResult(
            accused_character_id=intent.character_id,
            correct_culprit=correct,
            support_score=support_score,
            submitted_method=intent.method,
            submitted_motive=intent.motive,
            submitted_timeline=intent.timeline,
            method_supported=support_flags[0],
            motive_supported=support_flags[1],
            timeline_supported=support_flags[2],
            solved=solved,
            selected_evidence_ids=sorted(selected),
            selected_timeline_fact_ids=selected_timeline_facts,
            summary=("Your accusation is sufficiently supported." if solved else "Your accusation lacks sufficient support."),
        )
        # An accusation is a committed final action too: its result is visible
        # after the same ten-minute clock advance and batched NPC resolution as
        # any other committed investigation action.
        return self._commit(
            self.runtime.result.summary,
            npc_action_ids=npc_action_ids,
            defer_npc_phase=defer_npc_phase,
        )

    def _commit(
        self,
        narration: str,
        *,
        discoveries: list[PublicEvidenceView] | None = None,
        items: list[PublicItemView] | None = None,
        npc_action_ids: Mapping[str, str] | None = None,
        defer_npc_phase: bool = False,
    ) -> TurnResultView:
        self.runtime.turn += 1
        self.runtime.in_game_minute += self.case.turn_minutes
        events = [] if defer_npc_phase else self._run_npc_phase(npc_action_ids)
        if self.runtime.turn >= self.case.max_turns and self.runtime.phase != GamePhase.ENDED:
            self.runtime.phase = GamePhase.ENDED
            narration += " The investigation time has expired."
        return self._accept(True, narration, discoveries=discoveries or [], items=items or [], events=events)

    def _build_npc_planning_request(self) -> NpcIntentPlanningRequest:
        """Build one immutable, bounded request from the NPC turn-start state."""

        snapshot = {character_id: state.current_room_id for character_id, state in self.runtime.characters.items()}
        candidates = self._npc_candidate_sets(snapshot)
        return NpcIntentPlanningRequest(
            snapshot=SafeNpcTurnSnapshot(
                turn_number=self.runtime.turn,
                phase=self.runtime.phase.value,
                public_scene_summary=(
                    f"Investigation time is {self._time_label(self.runtime.in_game_minute)}. "
                    f"The investigator is in {self.location.rooms[self.runtime.player_room_id].name}."
                ),
                public_event_summaries=tuple(
                    event.narration[:360]
                    for event in self.runtime.event_log[-24:]
                    if event.visible_to_player
                ),
            ),
            actor_options=tuple(
                NpcActorActionOptions(
                    actor_id=character_id,
                    candidates=tuple(
                        NpcActionCandidate(
                            action_id=action_id,
                            summary=self._npc_candidate_summary(intent),
                        )
                        for action_id, intent in actor_candidates
                    ),
                )
                for character_id, actor_candidates in candidates.items()
            ),
        )

    def _build_private_npc_requests(
        self,
        public_request: NpcIntentPlanningRequest,
    ) -> tuple[PrivateNpcAgentRequest, ...]:
        """Partition canonical truth into one bounded briefing per survivor."""

        snapshot = {
            character_id: state.current_room_id
            for character_id, state in self.runtime.characters.items()
        }
        private_candidates = self._npc_candidate_sets(
            snapshot,
            include_private_social=True,
        )
        options_by_actor = {
            character_id: NpcActorActionOptions(
                actor_id=character_id,
                candidates=tuple(
                    NpcActionCandidate(
                        action_id=action_id,
                        summary=self._npc_candidate_summary(intent),
                    )
                    for action_id, intent in actor_candidates
                ),
            )
            for character_id, actor_candidates in private_candidates.items()
        }
        private_snapshot = SafeNpcTurnSnapshot(
            turn_number=public_request.snapshot.turn_number,
            phase=public_request.snapshot.phase,
            public_scene_summary=public_request.snapshot.public_scene_summary,
            public_event_summaries=tuple(
                summary[:240]
                for summary in public_request.snapshot.public_event_summaries[-8:]
            ),
        )
        requests: list[PrivateNpcAgentRequest] = []
        for character_id in sorted(options_by_actor):
            overlay = self.case.overlays[character_id]
            runtime = self.runtime.characters[character_id]
            try:
                card = load_character_card(character_id)
                extension = card.data.extensions.murder_mystery
                persona = (
                    f"Name: {card.data.name}. Identity: {extension.identity}. "
                    f"Personality: {card.data.personality}. "
                    f"Speaking style: {extension.speaking_style}."
                )
            except (OSError, ValueError):
                persona = f"Name: {self._name(character_id)}."
            briefing_parts = [
                f"Assigned role: {overlay.role.value}.",
                persona,
                f"Public relationship to victim: {overlay.public_relationship_to_victim}.",
                f"Private motive: {overlay.private_motive}.",
                f"Secrets: {'; '.join(overlay.secrets) or 'none'}.",
                f"Alibi claim: {overlay.alibi_claim}.",
                f"Goals: {'; '.join(overlay.goals) or 'none'}.",
                "Authorized lies: "
                + ("; ".join(lie.claim for lie in overlay.lies) or "none")
                + ".",
            ]
            private_facts: list[PrivateNpcFact] = []
            if character_id == self.case.murder.murderer_id:
                murder = self.case.murder
                # Put the crime truth first so the bounded fact window can
                # never evict the one fact the murderer must always retain.
                private_facts.append(
                    PrivateNpcFact(
                        id="host_murder_truth",
                        statement=(
                            f"You killed {self._name(murder.victim_id)} at "
                            f"{self._time_label(murder.minute)} in "
                            f"{self.location.rooms[murder.room_id].name}, using "
                            f"{murder.method}. Means: {murder.means}. Motive: "
                            f"{murder.motive}. Cover story: {murder.cover_story}."
                        )[:1_000],
                    )
                )
            private_facts.extend(
                PrivateNpcFact(
                    id=fact_id,
                    statement=self.case.facts[fact_id].statement[:1_000],
                )
                for fact_id in sorted(runtime.known_fact_ids)
                if fact_id in self.case.facts
            )
            belief_summary = "; ".join(
                f"{subject_id}={belief.suspicion} ({belief.summary})"
                for subject_id, belief in sorted(runtime.beliefs.items())
            )
            memory_summary = "; ".join(
                memory.text for memory in runtime.conversation_memory[-6:]
            )
            state_summary = (
                f"Room: {self.location.rooms[runtime.current_room_id].name}. "
                f"Activity: {runtime.current_activity}. Emotion: {runtime.emotional_state}. "
                f"Beliefs: {belief_summary or 'none'}. "
                f"Recent private memory: {memory_summary or 'none'}."
            )[:1_000]
            urgency = max(
                (belief.suspicion for belief in runtime.beliefs.values()),
                default=0,
            )
            character_summary = " ".join(briefing_parts)[:1_200]
            runtime_state = PrivateNpcRuntimeState(
                state_summary=state_summary,
                urgency=urgency,
            )

            def make_request(
                facts: tuple[PrivateNpcFact, ...],
            ) -> PrivateNpcAgentRequest:
                return PrivateNpcAgentRequest(
                    actor_id=character_id,
                    private_briefing=PrivateNpcBriefing(
                        character_summary=character_summary,
                        private_facts=facts,
                    ),
                    runtime_state=runtime_state,
                    snapshot=private_snapshot,
                    actor_options=options_by_actor[character_id],
                )

            accepted_facts: list[PrivateNpcFact] = []
            request = make_request(())
            for fact in private_facts[:24]:
                # Fill the fixed envelope without letting unusually wordy
                # facts abort an otherwise valid player turn. Important facts
                # remain first, including the murderer's crime truth.
                for statement_limit in (1_000, 720, 480, 240):
                    bounded_fact = fact.model_copy(
                        update={"statement": fact.statement[:statement_limit]}
                    )
                    try:
                        candidate = make_request(
                            tuple((*accepted_facts, bounded_fact))
                        )
                    except ValueError:
                        continue
                    accepted_facts.append(bounded_fact)
                    request = candidate
                    break
            requests.append(request)
        return tuple(requests)

    def _run_npc_phase(self, selected_action_ids: Mapping[str, str] | None = None) -> list[str]:
        """Resolve only engine-generated choices, with deterministic fallback."""

        snapshot = {character_id: state.current_room_id for character_id, state in self.runtime.characters.items()}
        candidate_sets = self._npc_candidate_sets(
            snapshot,
            include_private_social=True,
        )
        public_events: list[str] = []
        selected_social: list[tuple[str, _NpcSocialIntent]] = []
        for character_id, actor_candidates in candidate_sets.items():
            by_id = dict(actor_candidates)
            requested_id = selected_action_ids.get(character_id) if selected_action_ids else None
            intent = by_id.get(requested_id, actor_candidates[0][1])
            character = self.runtime.characters[character_id]
            if (
                intent.destination_room_id
                and intent.destination_room_id in set(self._unlocked_destinations(character.current_room_id))
            ):
                character.current_room_id = intent.destination_room_id
                character.current_activity = "moving"
            if (
                intent.manipulate_evidence_id
                and self._npc_may_manipulate(
                    character_id,
                    intent.manipulate_evidence_id,
                    snapshot,
                )
            ):
                evidence = self.runtime.evidence[intent.manipulate_evidence_id]
                evidence.condition = (
                    EvidenceCondition.DESTROYED if self.runtime.turn % 2 == 0 else EvidenceCondition.CONCEALED
                )
                evidence.current_slot_id = None
            if intent.social is not None:
                selected_social.append((character_id, intent.social))
            if character.current_room_id == self.runtime.player_room_id:
                self.runtime.player_knowledge.observed_character_room_ids[intent.character_id] = character.current_room_id
                public_events.append(f"{self._name(intent.character_id)} is now in the room.")
        social_participants: set[str] = set()
        for character_id, social in selected_social:
            if (
                character_id in social_participants
                or social.target_character_id in social_participants
            ):
                continue
            if self._resolve_private_social_action(character_id, social):
                social_participants.update(
                    (character_id, social.target_character_id)
                )
        self._resolve_private_exchanges(
            excluded_character_ids=social_participants
        )
        return public_events

    def _resolve_private_social_action(
        self,
        speaker_id: str,
        social: _NpcSocialIntent,
    ) -> bool:
        """Apply one pre-authorized private social choice, if still possible."""

        speaker = self.runtime.characters.get(speaker_id)
        listener = self.runtime.characters.get(social.target_character_id)
        if (
            speaker is None
            or listener is None
            or not speaker.alive
            or not listener.alive
            or speaker.current_room_id != listener.current_room_id
            or speaker.current_room_id == self.runtime.player_room_id
            or len(speaker.conversation_memory) >= MAX_CONVERSATION_MEMORIES
            or len(listener.conversation_memory) >= MAX_CONVERSATION_MEMORIES
            or any(
                fact_id not in speaker.known_fact_ids
                for fact_id in social.referenced_fact_ids
            )
        ):
            return False
        memory = ConversationMemoryEntry(
            turn=self.runtime.turn,
            speaker_id=speaker_id,
            listener_ids=[social.target_character_id],
            topic=social.topic,
            text=social.claim[:MAX_ACTION_CLAIM_LENGTH],
            referenced_fact_ids=list(social.referenced_fact_ids),
        )
        speaker.conversation_memory.append(memory)
        listener.conversation_memory.append(memory.model_copy(deep=True))
        speaker.current_activity = "speaking privately"
        listener.current_activity = "listening privately"
        if social.transfers_facts:
            listener.known_fact_ids.update(social.referenced_fact_ids)
        self._adjust_private_suspicion(social.target_character_id, speaker_id)
        return True

    def _resolve_private_exchanges(
        self,
        *,
        excluded_character_ids: set[str] | None = None,
    ) -> None:
        """Evolve social state without transferring facts or exposing dialogue.

        Living NPCs in rooms away from the investigator pair once, in stable
        ID order.  These exchanges affect only bounded suspicion, a small
        emotional vocabulary, and each participant's private memory.
        """

        excluded_character_ids = excluded_character_ids or set()
        occupants_by_room: dict[str, list[str]] = {}
        for character_id, character in sorted(self.runtime.characters.items()):
            if (
                not character.alive
                or character.current_room_id == self.runtime.player_room_id
            ):
                continue
            occupants_by_room.setdefault(character.current_room_id, []).append(
                character_id
            )

        for room_id in sorted(occupants_by_room):
            occupants = occupants_by_room[room_id]
            for index in range(0, len(occupants) - 1, 2):
                speaker_id, listener_id = occupants[index : index + 2]
                if (
                    speaker_id in excluded_character_ids
                    or listener_id in excluded_character_ids
                ):
                    continue
                if any(
                    len(self.runtime.characters[participant_id].conversation_memory)
                    >= MAX_CONVERSATION_MEMORIES
                    for participant_id in (speaker_id, listener_id)
                ):
                    continue
                self._adjust_private_suspicion(speaker_id, listener_id)
                self._adjust_private_suspicion(listener_id, speaker_id)
                memory = ConversationMemoryEntry(
                    turn=self.runtime.turn,
                    speaker_id=speaker_id,
                    listener_ids=[listener_id],
                    topic="private exchange",
                    text="They exchange guarded words away from the investigator.",
                    referenced_fact_ids=[],
                )
                self.runtime.characters[speaker_id].conversation_memory.append(
                    memory
                )
                self.runtime.characters[listener_id].conversation_memory.append(
                    memory.model_copy(deep=True)
                )

    def _adjust_private_suspicion(
        self,
        observer_id: str,
        subject_id: str,
    ) -> None:
        relationships = self.case.overlays[observer_id].relationships
        affinity = next(
            (
                relationship.affinity
                for relationship in relationships
                if relationship.target_character_id == subject_id
            ),
            0,
        )
        delta = 5 if affinity <= -25 else -3 if affinity >= 25 else 1
        observer = self.runtime.characters[observer_id]
        belief = observer.beliefs.setdefault(
            subject_id,
            BeliefState(subject_character_id=subject_id),
        )
        belief.suspicion = max(0, min(100, belief.suspicion + delta))
        belief.summary = (
            "Private contact increased unease."
            if delta > 0
            else "Private contact reduced immediate concern."
        )
        observer.emotional_state = "wary" if delta > 0 else "steadied"

    def _npc_candidate_sets(
        self,
        snapshot: Mapping[str, str],
        *,
        include_private_social: bool = False,
    ) -> dict[str, tuple[tuple[str, _NpcIntent], ...]]:
        """Return finite choices with the deterministic choice first."""

        candidate_sets: dict[str, tuple[tuple[str, _NpcIntent], ...]] = {}
        for character_id in sorted(snapshot):
            if not self.runtime.characters[character_id].alive:
                continue
            intents = [self._plan_npc(character_id, snapshot)]
            intents.append(_NpcIntent(character_id, None, None))
            intents.extend(
                _NpcIntent(character_id, destination, None)
                for destination in sorted(self._unlocked_destinations(snapshot[character_id]))
            )
            intents.extend(
                _NpcIntent(character_id, None, evidence_id)
                for evidence_id in sorted(self.runtime.evidence)
                if self._npc_may_manipulate(character_id, evidence_id, snapshot)
            )
            unique: list[_NpcIntent] = []
            seen: set[tuple[str | None, str | None]] = set()
            for intent in intents:
                identity = (intent.destination_room_id, intent.manipulate_evidence_id)
                if identity not in seen:
                    seen.add(identity)
                    unique.append(intent)
            choices: list[tuple[str, _NpcIntent]] = [
                (f"option_{index:02d}", intent) for index, intent in enumerate(unique)
            ]
            if include_private_social:
                for social in self._private_social_intents(character_id, snapshot):
                    if len(choices) >= MAX_CANDIDATES_PER_ACTOR:
                        break
                    choices.append(
                        (
                            self._private_social_action_id(social),
                            _NpcIntent(character_id, None, None, social),
                        )
                    )
            candidate_sets[character_id] = tuple(choices)
        return candidate_sets

    def _npc_candidate_summary(self, intent: _NpcIntent) -> str:
        if intent.destination_room_id:
            return f"Move by an available route to {self.location.rooms[intent.destination_room_id].name}."
        if intent.manipulate_evidence_id:
            return "Perform a currently permitted local interaction."
        if intent.social is not None:
            target_name = self._name(intent.social.target_character_id)
            if intent.social.topic == "private observation":
                return f"Privately share one known observation with {target_name}."
            if intent.social.topic == "private alibi":
                return f"Privately state an authored alibi to {target_name}."
            if intent.social.topic == "private authorized claim":
                return f"Privately make an authorized claim to {target_name}."
            return f"Privately react guardedly to {target_name} without making a factual claim."
        return "Remain in place."

    def _private_social_intents(
        self,
        character_id: str,
        snapshot: Mapping[str, str],
    ) -> tuple[_NpcSocialIntent, ...]:
        """Build at most three actor-local claims for one unobserved pair."""

        actor = self.runtime.characters[character_id]
        actor_room_id = snapshot[character_id]
        if (
            not actor.alive
            or actor_room_id == self.runtime.player_room_id
            or len(actor.conversation_memory) >= MAX_CONVERSATION_MEMORIES
        ):
            return ()
        target_id = next(
            (
                other_id
                for other_id in sorted(snapshot)
                if other_id != character_id
                and snapshot[other_id] == actor_room_id
                and self.runtime.characters[other_id].alive
                and len(self.runtime.characters[other_id].conversation_memory)
                < MAX_CONVERSATION_MEMORIES
            ),
            None,
        )
        if target_id is None:
            return ()

        overlay = self.case.overlays[character_id]
        intents: list[_NpcSocialIntent] = []

        def add(
            topic: str,
            claim: str,
            fact_ids: tuple[str, ...] = (),
            *,
            transfers_facts: bool = False,
        ) -> None:
            bounded_claim = claim[:MAX_ACTION_CLAIM_LENGTH]
            if not bounded_claim or self._private_claim_already_made(
                character_id,
                target_id,
                bounded_claim,
            ):
                return
            intents.append(
                _NpcSocialIntent(
                    target_character_id=target_id,
                    topic=topic,
                    claim=bounded_claim,
                    referenced_fact_ids=fact_ids,
                    transfers_facts=transfers_facts,
                )
            )

        add("private alibi", overlay.alibi_claim)
        observation = next(
            (
                item
                for item in sorted(overlay.observations, key=lambda item: item.id)
                if set(item.fact_ids) <= actor.known_fact_ids
                and not self._private_claim_already_made(
                    character_id,
                    target_id,
                    item.summary[:MAX_ACTION_CLAIM_LENGTH],
                )
            ),
            None,
        )
        if observation is not None:
            add(
                "private observation",
                observation.summary,
                observation.fact_ids,
                transfers_facts=True,
            )
        lie = next(
            (
                item
                for item in sorted(overlay.lies, key=lambda item: item.id)
                if not self._private_claim_already_made(
                    character_id,
                    target_id,
                    item.claim[:MAX_ACTION_CLAIM_LENGTH],
                )
            ),
            None,
        )
        if lie is not None:
            add("private authorized claim", lie.claim)
        if not intents:
            add(
                "private reaction",
                f"{self._name(character_id)} remains guarded and offers no factual claim.",
            )
        return tuple(intents[:3])

    @staticmethod
    def _private_social_action_id(social: _NpcSocialIntent) -> str:
        """Bind an opaque ID to the exact target and authorized semantics."""

        material = "\x1f".join(
            (
                social.target_character_id,
                social.topic,
                social.claim,
                ",".join(social.referenced_fact_ids),
                "1" if social.transfers_facts else "0",
            )
        ).encode("utf-8")
        return f"social_{hashlib.sha256(material).hexdigest()[:24]}"

    def _private_claim_already_made(
        self,
        speaker_id: str,
        listener_id: str,
        claim: str,
    ) -> bool:
        return any(
            memory.speaker_id == speaker_id
            and listener_id in memory.listener_ids
            and memory.text == claim
            for memory in self.runtime.characters[speaker_id].conversation_memory
        )

    def _plan_npc(self, character_id: str, snapshot: Mapping[str, str]) -> _NpcIntent:
        character = self.runtime.characters[character_id]
        if not character.alive:
            return _NpcIntent(character_id, None, None)
        neighbours = sorted(self._unlocked_destinations(snapshot[character_id]))
        destination = None
        if neighbours:
            offset = (self.case.seed + self.runtime.turn + list(sorted(snapshot)).index(character_id)) % len(neighbours)
            destination = neighbours[offset]
        manipulate = None
        if (
            character_id == self.case.murder.murderer_id
            and self.runtime.turn % 3 == 0
        ):
            for evidence_id, evidence in self.runtime.evidence.items():
                definition = self.case.evidence[evidence_id]
                if (
                    definition.manipulable
                    and not evidence.discovered_by_player
                    and evidence.current_slot_id
                    and self.location.evidence_slots[evidence.current_slot_id].room_id == snapshot[character_id]
                    and self.runtime.player_room_id != snapshot[character_id]
                ):
                    # Manipulating evidence is this NPC's action for the phase;
                    # they cannot also leave and affect their former room.  If
                    # solvability now forbids it, the exact deterministic
                    # fallback behaviour is to hold rather than move.
                    destination = None
                    manipulate = (
                        evidence_id
                        if self._npc_may_manipulate(character_id, evidence_id, snapshot)
                        else None
                    )
                    break
        return _NpcIntent(character_id, destination, manipulate)

    def _npc_may_manipulate(
        self,
        character_id: str,
        evidence_id: str,
        snapshot: Mapping[str, str],
    ) -> bool:
        """Recheck identity, presence, evidence, and solvability constraints."""

        if (
            character_id != self.case.murder.murderer_id
            or self.runtime.turn % 3 != 0
            or character_id not in snapshot
            or not self.runtime.characters[character_id].alive
            or self.runtime.characters[character_id].current_room_id != snapshot[character_id]
            or self.runtime.player_room_id == snapshot[character_id]
        ):
            return False
        evidence = self.runtime.evidence.get(evidence_id)
        definition = self.case.evidence.get(evidence_id)
        if (
            evidence is None
            or definition is None
            or not definition.manipulable
            or evidence.discovered_by_player
            or evidence.condition in {EvidenceCondition.COLLECTED, EvidenceCondition.CONCEALED, EvidenceCondition.DESTROYED}
            or evidence.current_slot_id is None
        ):
            return False
        slot = self.location.evidence_slots.get(evidence.current_slot_id)
        return bool(
            slot
            and slot.room_id == snapshot[character_id]
            and self._can_manipulate(evidence_id)
        )

    def _can_manipulate(self, evidence_id: str) -> bool:
        """Refuse a defensive action if removal would make a solution unsupported."""
        solution_ids = set(self.case.solution.method_evidence_ids) | set(self.case.solution.motive_evidence_ids) | set(self.case.solution.opportunity_evidence_ids)
        available = {
            candidate_id
            for candidate_id in solution_ids
            if candidate_id != evidence_id
            and self.runtime.evidence[candidate_id].condition not in {EvidenceCondition.DESTROYED, EvidenceCondition.CONCEALED}
        }
        groups = {self.case.evidence[candidate_id].redundancy_group for candidate_id in available}
        category_sets = (
            set(self.case.solution.method_evidence_ids),
            set(self.case.solution.motive_evidence_ids),
            set(self.case.solution.opportunity_evidence_ids),
        )
        return len(groups) >= self.case.solution.independent_evidence_groups_required and all(available & group for group in category_sets)

    def _discover_evidence(
        self,
        evidence_id: str,
        *,
        required_room_id: str | None = None,
    ) -> bool:
        runtime = self.runtime.evidence[evidence_id]
        if runtime.discovered_by_player or runtime.condition in {EvidenceCondition.CONCEALED, EvidenceCondition.DESTROYED}:
            return False
        definition = self.case.evidence[evidence_id]
        if required_room_id is not None and definition.initial_slot_id is not None:
            current_slot = (
                self.location.evidence_slots.get(runtime.current_slot_id)
                if runtime.current_slot_id is not None
                else None
            )
            if current_slot is None or current_slot.room_id != required_room_id:
                return False
        if any(
            prerequisite_id not in self.runtime.evidence
            or not self.runtime.evidence[prerequisite_id].discovered_by_player
            for prerequisite_id in definition.prerequisite_evidence_ids
        ):
            return False
        runtime.discovered_by_player = True
        runtime.discovered_by_character_ids.add(PLAYER_ID)
        runtime.discovered_turn = self.runtime.turn
        runtime.condition = EvidenceCondition.COLLECTED
        runtime.current_slot_id = None
        self.runtime.player_knowledge.discovered_evidence_ids.add(evidence_id)
        self.runtime.player_knowledge.known_fact_ids.update(definition.fact_ids)
        return True

    def _player_has_item(self, item_id: str) -> bool:
        item = self.runtime.items.get(item_id)
        return bool(item and item.discovered_by_player and item.holder_character_id == PLAYER_ID)

    def _door_between(self, source: str, destination: str):
        for door in self.location.doors:
            if door.room_a_id == source and door.room_b_id == destination:
                return door
            if not door.one_way and door.room_b_id == source and door.room_a_id == destination:
                return door
        return None

    def _unlocked_destinations(self, room_id: str) -> Iterable[str]:
        for door in self.location.doors:
            if self.runtime.doors[door.id].locked:
                continue
            if door.room_a_id == room_id:
                yield door.room_b_id
            elif not door.one_way and door.room_b_id == room_id:
                yield door.room_a_id

    def _opening_view(self) -> PublicOpeningView:
        opening = self.case.opening
        victim_id = self.case.murder.victim_id
        return PublicOpeningView(
            discoverer_id=opening.discoverer_id,
            discoverer_name=self._name(opening.discoverer_id),
            victim_id=victim_id,
            victim_name=self._name(victim_id),
            body_room_name=self.location.rooms[opening.body_room_id].name,
            body_condition=opening.body_condition,
            discoverer_observations=list(opening.discoverer_observations),
            containment_statement=opening.containment_statement,
            initial_reactions=[
                PublicStatementView(
                    speaker_id=character_id,
                    speaker_name=self._name(character_id),
                    text=text,
                    topic="opening reaction",
                )
                for character_id, text in sorted(opening.initial_reactions.items())
            ],
        )

    def _character_view(
        self,
        character_id: str,
        *,
        expose_emotion: bool = False,
    ) -> PublicCharacterView:
        overlay = self.case.overlays[character_id]
        public_hook = next(
            (
                item.public_hook
                for item in self.story_presentation.character_tensions
                if item.character_id == character_id
            ),
            overlay.public_relationship_to_victim,
        )
        return PublicCharacterView(
            id=character_id,
            name=self._name(character_id),
            description=public_hook,
            portrait_url=portrait_url(character_id),
            emotional_state=(
                self.runtime.characters[character_id].emotional_state
                if expose_emotion
                else ""
            ),
        )

    def _evidence_view(self, evidence_id: str) -> PublicEvidenceView:
        evidence = self.case.evidence[evidence_id]
        return PublicEvidenceView(id=evidence_id, name=evidence.name, description=evidence.description, kind=evidence.kind.value)

    def _fact_view(self, fact_id: str) -> PublicFactView:
        fact = self.case.facts[fact_id]
        return PublicFactView(id=fact.id, category=fact.category.value, statement=fact.statement)

    def _item_view(self, item_id: str) -> PublicItemView:
        item = self.location.items[item_id]
        return PublicItemView(id=item_id, name=item.name, description=item.description)

    def _statement_view(self, statement: StatementRecord) -> PublicStatementView:
        return PublicStatementView(
            id=statement.id,
            turn=statement.turn,
            minute=statement.minute,
            speaker_id=statement.speaker_id,
            speaker_name=self._name(statement.speaker_id),
            text=statement.claim,
            topic=statement.topic,
        )

    def _notebook_source_ids(self) -> set[str]:
        return (
            set(self.runtime.player_knowledge.discovered_evidence_ids)
            | set(self.runtime.player_knowledge.known_fact_ids)
            | {statement.id for statement in self.runtime.player_knowledge.statements}
        )

    def _result_view(self) -> PublicResultView | None:
        result = self.runtime.result
        if result is None:
            return None
        return PublicResultView(
            accused_character_id=result.accused_character_id,
            correct_culprit=result.correct_culprit,
            support_score=result.support_score,
            method_supported=result.method_supported,
            motive_supported=result.motive_supported,
            timeline_supported=result.timeline_supported,
            solved=result.solved,
            summary=result.summary,
        )

    def _name(self, character_id: str) -> str:
        try:
            return load_character_card(character_id).data.name
        except (OSError, ValueError):
            return " ".join(part.capitalize() for part in character_id.split("_"))

    @staticmethod
    def _time_label(minute: int) -> str:
        return f"{(minute // 60) % 24:02d}:{minute % 60:02d}"

    def _accept(
        self,
        committed: bool,
        narration: str,
        *,
        discoveries: list[PublicEvidenceView] | None = None,
        items: list[PublicItemView] | None = None,
        dialogue: PublicStatementView | None = None,
        events: list[str] | None = None,
    ) -> TurnResultView:
        return TurnResultView(
            accepted=True,
            committed=committed,
            narration=narration,
            discoveries=discoveries or [],
            items=items or [],
            dialogue=dialogue,
            events=events or [],
            game=self.view(),
        )

    def _reject(self, narration: str) -> TurnResultView:
        return TurnResultView(accepted=False, committed=False, narration=narration, game=self.view())
