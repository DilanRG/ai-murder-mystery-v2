"""Deterministic authoritative turn engine for the Ashwick vertical slice."""

from __future__ import annotations

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
from game.models import (
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
    LocationPackage,
    SearchableObjectRuntimeState,
    StatementRecord,
    PlayerTimelineEntry,
    WeaponRuntimeState,
    WorldRuntimeState,
)
from game.npc_planning import (
    NpcActionCandidate,
    NpcActorActionOptions,
    NpcIntentPlanningRequest,
    SafeNpcTurnSnapshot,
)
from game.validator import validate_case
from game.public_assets import portrait_url
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
    PublicTimelineEntryView,
    TurnResultView,
)


PLAYER_ID = "player"


@dataclass(frozen=True)
class _NpcIntent:
    """A turn-start NPC decision; resolution happens later in initiative order."""

    character_id: str
    destination_room_id: str | None
    manipulate_evidence_id: str | None


@dataclass(frozen=True)
class EngineActionPreview:
    """Result of applying a command to a deep-copied runtime only."""

    result: TurnResultView
    npc_request: NpcIntentPlanningRequest | None


class GameEngine:
    """Owns mutable runtime state while retaining immutable authored truth."""

    def __init__(self, case: CaseDefinition, location: LocationPackage) -> None:
        report = validate_case(case, location)
        if not report.valid:
            raise ValueError(f"cannot start invalid case: {report.issues!r}")
        self.case = case
        self.location = location
        self.runtime = self._initial_runtime()

    @classmethod
    def create(cls, case: CaseDefinition, location: LocationPackage) -> "GameEngine":
        return cls(case, location)

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
            self._character_view(character_id)
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
            case_title=self.case.title,
            phase=self.runtime.phase.value,
            turn=self.runtime.turn,
            in_game_minute=self.runtime.in_game_minute,
            time_label=self._time_label(self.runtime.in_game_minute),
            player_room=PublicRoomView(
                id=room.id,
                name=room.name,
                description=room.description,
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
    ) -> TurnResultView:
        """Apply an intent synchronously, retaining deterministic NPC fallback.

        ``npc_action_ids`` may contain only IDs from a request produced by this
        engine.  The NPC phase rebuilds and validates the finite candidate set
        before resolving them; absent or stale IDs fall back deterministically.
        """

        return self._apply(
            intent,
            npc_action_ids=npc_action_ids,
            defer_npc_phase=False,
        )

    def preview(self, intent: PlayerIntent | dict[str, object]) -> EngineActionPreview:
        """Preview against a deep copy and capture the post-player NPC request.

        Provider latency and cancellation therefore happen before the original
        runtime is touched.  Canonical case/location models are frozen and may
        be shared; every mutable runtime model is copied recursively.
        """

        clone = object.__new__(GameEngine)
        clone.case = self.case
        clone.location = self.location
        clone.runtime = self.runtime.model_copy(deep=True)
        result = clone._apply(intent, npc_action_ids=None, defer_npc_phase=True)
        request = clone._build_npc_planning_request() if result.accepted and result.committed else None
        return EngineActionPreview(result=result, npc_request=request)

    def _apply(
        self,
        intent: PlayerIntent | dict[str, object],
        *,
        npc_action_ids: Mapping[str, str] | None,
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
            return self._interview_exchange(command)
        if isinstance(command, EndInterviewIntent):
            return self._end_interview(npc_action_ids, defer_npc_phase)
        if isinstance(command, ExamineEvidenceIntent):
            return self._examine(command, npc_action_ids, defer_npc_phase)
        if isinstance(command, (ExamineSceneIntent, ExamineBodyIntent)):
            return self._examine_body(command, npc_action_ids, defer_npc_phase)
        if isinstance(command, ReviewNotebookIntent):
            return self._accept(False, "You review the notes without spending investigation time.")
        if isinstance(command, AddNoteIntent):
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

    def _interview_exchange(self, intent: InterviewExchangeIntent) -> TurnResultView:
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
        index = session.exchanges_used
        # Only authored observations carry fact references.  Alibis and lies
        # are still recordable character claims, but must not accidentally
        # bless hidden truth with a canonical fact ID.
        choices = [
            (overlay.alibi_claim, []),
            *[(item.summary, list(item.fact_ids)) for item in overlay.observations],
            *[(lie.claim, []) for lie in overlay.lies],
        ]
        text, referenced_fact_ids = (
            choices[index % len(choices)] if choices else ("I have nothing useful to add.", [])
        )
        statement = StatementRecord(
            id=f"statement_{self.runtime.turn}_{session.character_id}_{index}",
            turn=self.runtime.turn,
            minute=self.runtime.in_game_minute,
            speaker_id=session.character_id,
            audience_ids=[PLAYER_ID],
            topic=(intent.message.strip()[:80] or "interview"),
            claim=text,
            referenced_fact_ids=referenced_fact_ids,
            source="deterministic_fallback",
        )
        self.runtime.player_knowledge.statements.append(statement)
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
            if route in definition.discoverable_via and self._discover_evidence(evidence_id):
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
            if "examine:body" in definition.discoverable_via and self._discover_evidence(evidence_id):
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
        selected = submitted_evidence if submitted_evidence else set(self.runtime.player_knowledge.discovered_evidence_ids)
        selected &= self.runtime.player_knowledge.discovered_evidence_ids
        solution = self.case.solution
        method_claim_ok = self._claim_matches_known_fact(
            intent.method,
            candidate_fact_ids=self._known_facts_linked_to(
                solution.method_evidence_ids,
                category="means",
            ),
        )
        motive_claim_ok = self._claim_matches_known_fact(
            intent.motive,
            candidate_fact_ids=self._known_facts_linked_to(
                solution.motive_evidence_ids,
                category="motive",
            ),
        )
        timeline_claim_ok = self._claim_matches_known_fact(
            intent.timeline,
            candidate_fact_ids=set(solution.timeline_fact_ids) & self.runtime.player_knowledge.known_fact_ids,
        )
        # Evidence is the authoritative support.  The explicit method, motive,
        # and timeline inputs are checked when supplied, so an evidence-backed
        # but internally inconsistent accusation cannot receive that component.
        support_score = sum((
            bool(selected & set(solution.method_evidence_ids)) and method_claim_ok,
            bool(selected & set(solution.motive_evidence_ids)) and motive_claim_ok,
            bool(selected & set(solution.opportunity_evidence_ids)) and timeline_claim_ok,
        ))
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
            method_supported=bool(selected & set(solution.method_evidence_ids)) and method_claim_ok,
            motive_supported=bool(selected & set(solution.motive_evidence_ids)) and motive_claim_ok,
            timeline_supported=bool(selected & set(solution.opportunity_evidence_ids)) and timeline_claim_ok,
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

    def _run_npc_phase(self, selected_action_ids: Mapping[str, str] | None = None) -> list[str]:
        """Resolve only engine-generated choices, with deterministic fallback."""

        snapshot = {character_id: state.current_room_id for character_id, state in self.runtime.characters.items()}
        candidate_sets = self._npc_candidate_sets(snapshot)
        public_events: list[str] = []
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
            if character.current_room_id == self.runtime.player_room_id:
                self.runtime.player_knowledge.observed_character_room_ids[intent.character_id] = character.current_room_id
                public_events.append(f"{self._name(intent.character_id)} is now in the room.")
        return public_events

    def _npc_candidate_sets(
        self, snapshot: Mapping[str, str]
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
            candidate_sets[character_id] = tuple(
                (f"option_{index:02d}", intent) for index, intent in enumerate(unique)
            )
        return candidate_sets

    def _npc_candidate_summary(self, intent: _NpcIntent) -> str:
        if intent.destination_room_id:
            return f"Move by an available route to {self.location.rooms[intent.destination_room_id].name}."
        if intent.manipulate_evidence_id:
            return "Perform a currently permitted local interaction."
        return "Remain in place."

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

    def _discover_evidence(self, evidence_id: str) -> bool:
        runtime = self.runtime.evidence[evidence_id]
        if runtime.discovered_by_player or runtime.condition in {EvidenceCondition.CONCEALED, EvidenceCondition.DESTROYED}:
            return False
        runtime.discovered_by_player = True
        runtime.discovered_by_character_ids.add(PLAYER_ID)
        runtime.discovered_turn = self.runtime.turn
        runtime.condition = EvidenceCondition.COLLECTED
        runtime.current_slot_id = None
        self.runtime.player_knowledge.discovered_evidence_ids.add(evidence_id)
        self.runtime.player_knowledge.known_fact_ids.update(self.case.evidence[evidence_id].fact_ids)
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

    def _character_view(self, character_id: str) -> PublicCharacterView:
        overlay = self.case.overlays[character_id]
        return PublicCharacterView(
            id=character_id,
            name=self._name(character_id),
            description=overlay.public_relationship_to_victim,
            portrait_url=portrait_url(character_id),
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

    @staticmethod
    def _statement_view(statement: StatementRecord) -> PublicStatementView:
        return PublicStatementView(
            id=statement.id,
            turn=statement.turn,
            minute=statement.minute,
            speaker_id=statement.speaker_id,
            speaker_name=" ".join(part.capitalize() for part in statement.speaker_id.split("_")),
            text=statement.claim,
            topic=statement.topic,
        )

    def _notebook_source_ids(self) -> set[str]:
        return (
            set(self.runtime.player_knowledge.discovered_evidence_ids)
            | set(self.runtime.player_knowledge.known_fact_ids)
            | {statement.id for statement in self.runtime.player_knowledge.statements}
        )

    def _known_facts_linked_to(
        self,
        solution_evidence_ids: Iterable[str],
        *,
        category: str,
    ) -> set[str]:
        solution_evidence = set(solution_evidence_ids)
        return {
            fact_id
            for fact_id in self.runtime.player_knowledge.known_fact_ids
            if fact_id in self.case.facts
            and self.case.facts[fact_id].category.value == category
            and set(self.case.facts[fact_id].related_evidence_ids) & solution_evidence
        }

    def _claim_matches_known_fact(self, claim: str, *, candidate_fact_ids: Iterable[str]) -> bool:
        if not claim.strip():
            return False
        expected = {
            self._normalise(self.case.facts[fact_id].statement)
            for fact_id in candidate_fact_ids
            if fact_id in self.case.facts
        }
        return self._normalise(claim) in expected

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
        return " ".join(part.capitalize() for part in character_id.split("_"))

    @staticmethod
    def _time_label(minute: int) -> str:
        return f"{(minute // 60) % 24:02d}:{minute % 60:02d}"

    @staticmethod
    def _normalise(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

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
