"""Application service for the deterministic Ashwick game session.

The service is deliberately small: it owns the one in-process engine and
coordinates validated saves.  HTTP handlers consume only its public views;
they never hand the canonical case or runtime models to a client.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from game.actions import InterviewExchangeIntent, PlayerIntent, parse_player_intent
from game.content import (
    CHARACTER_CARDS_DIR,
    list_content_ids,
    load_case,
    load_character_card,
    load_location,
)
from game.public_assets import portrait_url
from game.engine import GameEngine
from game.npc_planning import (
    ConstrainedNpcIntentPlanningCoordinator,
    OpenRouterNpcIntentBatchAdapter,
)
from game.persistence import SaveValidationError, load_engine, write_save
from game.portrayal import (
    ConstrainedPortrayalCoordinator,
    OpenRouterPortrayalAdapter,
    PermittedFact,
    PortrayalRequest,
    PublicDialogueLine,
)
from game.views import PlayerGameView, TurnResultView


DEFAULT_CASE_ID = "ashwick_sample"
DEFAULT_LOCATION_ID = "ashwick_manor"


class GameService:
    """Single-session facade used by the FastAPI application."""

    def __init__(self, save_root: Path | str, llm: Any | None = None) -> None:
        self.save_root = Path(save_root)
        self.llm = llm
        self.engine: GameEngine | None = None
        self._action_lock = asyncio.Lock()

    def is_active(self) -> bool:
        return self.engine is not None and self.engine.runtime.phase.value != "ended"

    def start(
        self,
        *,
        case_id: str = DEFAULT_CASE_ID,
        location_id: str = DEFAULT_LOCATION_ID,
    ) -> PlayerGameView:
        case = load_case(case_id)
        location = load_location(location_id)
        if case.location_package_id != location.id:
            raise ValueError("case and location package are not compatible")
        self.engine = GameEngine.create(case, location)
        return self.engine.view()

    async def start_async(
        self,
        *,
        case_id: str = DEFAULT_CASE_ID,
        location_id: str = DEFAULT_LOCATION_ID,
    ) -> PlayerGameView:
        """Replace the session only while no action or load can be in flight."""

        async with self._action_lock:
            return self.start(case_id=case_id, location_id=location_id)

    def state(self) -> PlayerGameView:
        return self._require_engine().view()

    def apply(self, payload: dict[str, object]) -> TurnResultView:
        return self._require_engine().apply(payload)

    async def action(self, intent: PlayerIntent | dict[str, object]) -> dict[str, object]:
        """Preview and plan safely, then apply one authoritative command.

        A committed action is first exercised on a deep-copied runtime.  The
        optional remote NPC planner sees only that preview's frozen candidate
        request, while the real runtime remains unchanged.  The same lock also
        excludes new/load session replacement.  Dialogue portrayal remains an
        optional post-commit presentation pass.
        """

        async with self._action_lock:
            return await self._action_locked(intent)

    async def _action_locked(
        self, intent: PlayerIntent | dict[str, object]
    ) -> dict[str, object]:
        command = parse_player_intent(intent) if isinstance(intent, dict) else intent
        engine = self._require_engine()
        preview = engine.preview(command)
        npc_action_ids: dict[str, str] | None = None
        if preview.result.accepted and preview.result.committed and preview.npc_request is not None:
            coordinator = ConstrainedNpcIntentPlanningCoordinator(
                OpenRouterNpcIntentBatchAdapter(self.llm) if self.llm is not None else None
            )
            plan = await coordinator.plan(preview.npc_request)
            npc_action_ids = {
                selection.actor_id: selection.action_id
                for selection in plan.selections
            }

        result = engine.apply(command, npc_action_ids=npc_action_ids)
        response = result.model_dump(mode="json")
        if not isinstance(command, InterviewExchangeIntent) or not result.accepted or result.dialogue is None:
            return response

        statement = next(
            (
                item
                for item in engine.runtime.player_knowledge.statements
                if item.id == result.dialogue.id
            ),
            None,
        )
        if statement is None:
            return response

        # This entire presentation pass is deliberately post-commit and
        # best-effort.  Missing card data or an adapter/configuration error
        # must never make a successful, already-recorded engine turn fail.
        try:
            character_id = statement.speaker_id
            card = load_character_card(character_id)
            known_fact_ids = engine.runtime.player_knowledge.known_fact_ids
            permitted_facts = tuple(
                PermittedFact(id=fact_id, statement=engine.case.facts[fact_id].statement)
                for fact_id in statement.referenced_fact_ids
                if fact_id in known_fact_ids and fact_id in engine.case.facts
            )
            transcript = tuple(
                PublicDialogueLine(
                    speaker_name=self._display_name(previous.speaker_id),
                    utterance=previous.claim,
                )
                for previous in engine.runtime.player_knowledge.statements[:-1][-16:]
            )
            request = PortrayalRequest(
                character_id=character_id,
                character_name=result.dialogue.speaker_name,
                speaking_style=card.data.extensions.murder_mystery.speaking_style,
                emotional_state=self._public_emotional_state(
                    engine.runtime.characters[character_id].emotional_state
                ),
                player_question=command.message,
                canonical_claim=statement.claim,
                permitted_facts=permitted_facts,
                prior_public_dialogue=transcript,
            )
            coordinator = ConstrainedPortrayalCoordinator(
                OpenRouterPortrayalAdapter(self.llm) if self.llm is not None else None
            )
            response["portrayal"] = (
                await coordinator.portray(request)
            ).model_dump(mode="json")
        except Exception:
            return response
        return response

    def save(self, filename: str) -> str:
        if not filename.lower().endswith(".json"):
            filename = f"{filename}.json"
        return write_save(self._require_engine(), self.save_root, filename).name

    def list_saves(self) -> list[str]:
        if not self.save_root.exists():
            return []
        return sorted(path.name for path in self.save_root.glob("*.json") if path.is_file())

    def load(self, filename: str) -> PlayerGameView:
        self.engine = load_engine(self.save_root, filename)
        return self.engine.view()

    async def load_async(self, filename: str) -> PlayerGameView:
        """Restore a session only while no preview/provider/apply is active."""

        async with self._action_lock:
            return self.load(filename)

    def catalog(self) -> dict[str, object]:
        """Return public, fixed content only; case truth is intentionally absent."""

        location = load_location(DEFAULT_LOCATION_ID)
        return {
            "default_case_id": DEFAULT_CASE_ID,
            "default_location_id": DEFAULT_LOCATION_ID,
            "locations": [self._location_summary(location)],
            "characters": [
                self._character_summary(character_id)
                for character_id in list_content_ids(CHARACTER_CARDS_DIR)
            ],
        }

    def bootstrap(self) -> dict[str, object]:
        return {"catalog": self.catalog(), "game": self.engine.view() if self.engine else None}

    def debrief(self) -> dict[str, object]:
        """Construct a deliberate post-game reveal after the case has ended."""

        engine = self._require_engine()
        if engine.runtime.phase.value != "ended":
            raise ValueError("Game not ended.")
        case = engine.case
        solution = case.solution
        evidence_ids = (
            *solution.method_evidence_ids,
            *solution.motive_evidence_ids,
            *solution.opportunity_evidence_ids,
        )
        unique_evidence_ids = list(dict.fromkeys(evidence_ids))
        return {
            "case_title": case.title,
            "outcome": engine.view().result.model_dump(mode="json") if engine.view().result else None,
            "solution": {
                "culprit_id": solution.culprit_id,
                "culprit_name": self._display_name(solution.culprit_id),
                "victim_id": case.murder.victim_id,
                "victim_name": self._display_name(case.murder.victim_id),
                "method": case.murder.method,
                "means": case.murder.means,
                "motive": case.murder.motive,
                "opportunity": case.murder.opportunity,
                "cover_story": case.murder.cover_story,
                "supporting_evidence": [
                    {
                        "id": evidence_id,
                        "name": case.evidence[evidence_id].name,
                        "description": case.evidence[evidence_id].description,
                    }
                    for evidence_id in unique_evidence_ids
                ],
                "timeline_facts": [
                    {
                        "id": fact_id,
                        "statement": case.facts[fact_id].statement,
                    }
                    for fact_id in solution.timeline_fact_ids
                ],
            },
        }

    def _require_engine(self) -> GameEngine:
        if self.engine is None:
            raise ValueError("No active game.")
        return self.engine

    @staticmethod
    def _display_name(character_id: str) -> str:
        return " ".join(part.capitalize() for part in character_id.split("_"))

    @staticmethod
    def _public_emotional_state(runtime_state: str) -> str:
        """Map internal wording to a small, public-safe presentation vocabulary."""

        state = runtime_state.lower()
        if "angry" in state or "grief" in state:
            return "distressed"
        if "frightened" in state or "anxious" in state:
            return "uneasy"
        if "defensive" in state:
            return "guarded"
        if "focused" in state:
            return "focused"
        if "alert" in state:
            return "alert"
        if "controlled" in state or "composed" in state:
            return "composed"
        return "guarded"

    @staticmethod
    def _location_summary(location: Any) -> dict[str, object]:
        return {
            "id": location.id,
            "name": location.name,
            "subtitle": location.subtitle,
            "description": location.description,
            "isolation_premise": location.isolation_premise,
            "assembly_room_id": location.assembly_room_id,
            "rooms": [
                {
                    "id": room.id,
                    "name": room.name,
                    "short_name": room.short_name,
                    "description": room.description,
                    "atmosphere": room.atmosphere,
                    "searchable_object_ids": list(room.searchable_object_ids),
                    "tags": list(room.tags),
                }
                for room in location.rooms.values()
            ],
            "doors": [
                {
                    "id": door.id,
                    "room_a_id": door.room_a_id,
                    "room_b_id": door.room_b_id,
                    "travel_minutes": door.travel_minutes,
                    "locked_by_default": door.locked_by_default,
                    "one_way": door.one_way,
                }
                for door in location.doors
            ],
            "searchable_objects": [
                {
                    "id": obj.id,
                    "room_id": obj.room_id,
                    "name": obj.name,
                    "description": obj.description,
                    "difficulty": obj.difficulty.value,
                    "requires_item_id": obj.requires_item_id,
                }
                for obj in location.searchable_objects.values()
            ],
            "movement_constraints": list(location.movement_constraints),
            "visual_theme": location.visual_theme.model_dump(mode="json"),
        }

    @staticmethod
    def _character_summary(character_id: str) -> dict[str, object]:
        card = load_character_card(character_id)
        extension = card.data.extensions.murder_mystery
        return {
            "id": character_id,
            "name": card.data.name,
            "description": card.data.description,
            "tags": list(card.data.tags),
            "identity": extension.identity,
            "public_biography": extension.public_biography,
            "appearance": extension.appearance,
            "speaking_style": extension.speaking_style,
            "portrait_url": portrait_url(character_id),
        }


__all__ = ["DEFAULT_CASE_ID", "DEFAULT_LOCATION_ID", "GameService", "SaveValidationError"]
