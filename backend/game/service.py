"""Application service for the deterministic AI Murder Mystery Game session.

The service is deliberately small: it owns the one in-process engine and
coordinates validated saves.  HTTP handlers consume only its public views;
they never hand the canonical case or runtime models to a client.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from game.actions import InterviewExchangeIntent, PlayerIntent, parse_player_intent
from game.case_generation import generate_validated_scenario, select_generation_cast
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
from game.persistence import (
    SaveValidationError,
    load_engine,
    snapshot_engine,
    write_save,
)
from game.recipes import (
    ASSEMBLIES_DIR,
    CaseRecipeSelection,
    load_case_recipe,
    resolve_materialized_case_recipe,
)
from game.portrayal import (
    ConstrainedPortrayalCoordinator,
    DeterministicPortrayalFallback,
    OpenRouterPortrayalAdapter,
    PermittedFact,
    PortrayalRequest,
    PublicDialogueLine,
)
from game.private_npc_agents import (
    OpenRouterPrivateNpcAgentAdapter,
    PrivateNpcAgentCoordinator,
)
from game.private_interview import (
    OpenRouterPrivateInterviewSelectionAdapter,
    PrivateInterviewSelectionCoordinator,
)
from game.views import PlayerGameView, TurnResultView


DEFAULT_CASE_ID = "ashwick_sample"
DEFAULT_LOCATION_ID = "ashwick_manor"
DEFAULT_RECIPE_ID = "ashwick_manor_dual_spines"


class GameService:
    """Single-session facade used by the FastAPI application."""

    def __init__(
        self,
        save_root: Path | str,
        llm: Any | None = None,
        *,
        scenario_llm: Any | None = None,
        npc_llm: Any | None = None,
        portrayal_llm: Any | None = None,
    ) -> None:
        self.save_root = Path(save_root)
        # ``llm`` remains the production/default provider for compatibility.
        # Experiment-only role overrides allow crossed scenario/NPC evaluation
        # without changing accepted canonical truth or the ordinary settings UI.
        self.llm = llm
        self._scenario_llm = scenario_llm
        self._npc_llm = npc_llm
        self._portrayal_llm = portrayal_llm
        self.engine: GameEngine | None = None
        self._generation_metadata: dict[str, object] | None = None
        self._action_lock = asyncio.Lock()

    def is_active(self) -> bool:
        return self.engine is not None and self.engine.runtime.phase.value != "ended"

    async def replace_llm(self, llm: Any | None) -> None:
        """Replace provider settings only between generation/action transactions."""

        async with self._action_lock:
            self.llm = llm

    async def replace_role_llms(
        self,
        *,
        scenario_llm: Any | None,
        npc_llm: Any | None,
        portrayal_llm: Any | None = None,
    ) -> None:
        """Atomically configure explicit experiment-only provider roles."""

        async with self._action_lock:
            self._scenario_llm = scenario_llm
            self._npc_llm = npc_llm
            self._portrayal_llm = portrayal_llm

    def _scenario_provider(self) -> Any | None:
        return self._scenario_llm if self._scenario_llm is not None else self.llm

    def _npc_provider(self) -> Any | None:
        return self._npc_llm if self._npc_llm is not None else self.llm

    def _portrayal_provider(self) -> Any | None:
        if self._portrayal_llm is not None:
            return self._portrayal_llm
        return self._npc_provider()

    def start(
        self,
        *,
        case_id: str = DEFAULT_CASE_ID,
        location_id: str = DEFAULT_LOCATION_ID,
        recipe_selection: CaseRecipeSelection | None = None,
    ) -> PlayerGameView:
        case = load_case(case_id)
        location = load_location(location_id)
        if case.location_package_id != location.id:
            raise ValueError("case and location package are not compatible")
        candidate = GameEngine.create(
            case,
            location,
            recipe_selection=recipe_selection,
        )
        self.engine = candidate
        self._generation_metadata = None
        return self.engine.view()

    def start_recipe(
        self,
        *,
        recipe_id: str,
        seed: int,
        character_ids: tuple[str, ...] | None = None,
    ) -> PlayerGameView:
        """Resolve a seed to a complete authored spine and compatible cast."""

        selection, case = resolve_materialized_case_recipe(
            recipe_id,
            seed,
            selected_character_ids=character_ids,
        )
        recipe = load_case_recipe(recipe_id)
        location = load_location(recipe.location_package_id)
        candidate = GameEngine.create(
            case,
            location,
            recipe_selection=selection,
        )
        self.engine = candidate
        self._generation_metadata = None
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

    async def start_recipe_async(
        self,
        *,
        recipe_id: str,
        seed: int,
        character_ids: tuple[str, ...] | None = None,
    ) -> PlayerGameView:
        """Replace the session with a reproducible recipe selection under the lock."""

        async with self._action_lock:
            selection, case = resolve_materialized_case_recipe(
                recipe_id,
                seed,
                selected_character_ids=character_ids,
            )
            recipe = load_case_recipe(recipe_id)
            location = load_location(recipe.location_package_id)
            candidate = GameEngine.create(
                case,
                location,
                recipe_selection=selection,
            )
            self.engine = candidate
            self._generation_metadata = None
            return self.engine.view()

    async def start_generated_async(
        self,
        *,
        seed: int,
        location_id: str = DEFAULT_LOCATION_ID,
        character_ids: tuple[str, ...] | None = None,
        difficulty: str = "normal",
    ) -> PlayerGameView:
        """Generate and validate a complete case before replacing the session."""

        async with self._action_lock:
            provider = self._scenario_provider()
            selected_character_ids = select_generation_cast(
                seed=seed,
                character_ids=character_ids,
            )
            location = load_location(location_id)
            generated = await generate_validated_scenario(
                provider,
                character_ids=selected_character_ids,
                location=location,
                seed=seed,
                difficulty=difficulty,
            )
            candidate = GameEngine.create(
                generated.case,
                location,
                story_presentation=generated.presentation,
            )
            self.engine = candidate
            self._generation_metadata = {
                "mode": "generated",
                "seed": seed,
                "cast_mode": "manual" if character_ids is not None else "automatic",
                "location_id": location.id,
                "story_source": "openrouter",
                "story_status": "ready",
            }
            return candidate.view()

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
        npc_action_sources: dict[str, str] | None = None
        interview_response_id: str | None = None
        if (
            isinstance(command, InterviewExchangeIntent)
            and preview.result.accepted
            and self._generation_metadata is not None
            and preview.private_interview_request is not None
        ):
            npc_provider = self._npc_provider()
            coordinator = PrivateInterviewSelectionCoordinator(
                OpenRouterPrivateInterviewSelectionAdapter(npc_provider)
                if npc_provider is not None
                else None
            )
            plan = await coordinator.select(preview.private_interview_request)
            interview_response_id = plan.selection.response_id
        elif (
            preview.result.accepted
            and preview.result.committed
            and self._generation_metadata is not None
            and preview.private_npc_requests is not None
        ):
            npc_provider = self._npc_provider()
            coordinator = PrivateNpcAgentCoordinator(
                OpenRouterPrivateNpcAgentAdapter(npc_provider)
                if npc_provider is not None
                else None
            )
            plan = await coordinator.plan_all(preview.private_npc_requests)
            npc_action_ids = {
                actor_id: selection.action_id
                for actor_id, selection in plan.selections.items()
            }
            npc_action_sources = {
                actor_id: source.value
                for actor_id, source in plan.sources.items()
            }
        elif preview.result.accepted and preview.result.committed and preview.npc_request is not None:
            npc_provider = self._npc_provider()
            coordinator = ConstrainedNpcIntentPlanningCoordinator(
                OpenRouterNpcIntentBatchAdapter(npc_provider)
                if npc_provider is not None
                else None
            )
            plan = await coordinator.plan(preview.npc_request)
            npc_action_ids = {
                selection.actor_id: selection.action_id
                for selection in plan.selections
            }
            npc_action_sources = {
                selection.actor_id: plan.source.value
                for selection in plan.selections
            }

        result = engine.apply(
            command,
            npc_action_ids=npc_action_ids,
            npc_action_sources=npc_action_sources,
            interview_response_id=interview_response_id,
        )
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
            portrayal_provider = self._portrayal_provider()
            coordinator = ConstrainedPortrayalCoordinator(
                OpenRouterPortrayalAdapter(portrayal_provider)
                if portrayal_provider is not None
                else None
            )
            response["portrayal"] = (
                await coordinator.portray(request)
            ).model_dump(mode="json")
        except asyncio.CancelledError:
            # The authoritative exchange is already committed.  Returning its
            # deterministic portrayal keeps cancellation from turning a
            # successful action into an apparently retryable failure.
            response["portrayal"] = DeterministicPortrayalFallback().portray(
                request
            ).model_dump(mode="json")
            return response
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
        self._generation_metadata = (
            {
                "mode": "generated",
                "seed": self.engine.case.seed,
                "cast_mode": "restored",
                "location_id": self.engine.location.id,
                "story_source": "openrouter",
                "story_status": "ready",
            }
            if self.engine.case.id.startswith("generated_")
            else None
        )
        return self.engine.view()

    async def load_async(self, filename: str) -> PlayerGameView:
        """Restore a session only while no preview/provider/apply is active."""

        async with self._action_lock:
            return self.load(filename)

    def catalog(self) -> dict[str, object]:
        """Return public content choices; canonical case truth stays absent."""

        location = load_location(DEFAULT_LOCATION_ID)
        recipes = []
        for recipe_id in list_content_ids(ASSEMBLIES_DIR):
            recipe = load_case_recipe(recipe_id)
            cast_variations = 1
            for slot in recipe.cast_slots:
                cast_variations *= len(slot.candidate_card_ids)
            total_variations = len(recipe.case_ids) * cast_variations
            character_pool_size = sum(
                len(slot.candidate_card_ids) for slot in recipe.cast_slots
            )
            recipes.append(
                {
                    "id": recipe.id,
                    "name": "Offline demo: authored Ashwick mystery",
                    "description": (
                        f"A provider-free test fixture selecting one of {len(recipe.case_ids)} "
                        f"authored mysteries and a compatible cast from {character_pool_size} cards."
                    ),
                    "location_package_id": recipe.location_package_id,
                    "variation_count": total_variations,
                    "cast_variation_count": cast_variations,
                    "character_pool_size": character_pool_size,
                    "cast_groups": [
                        {
                            "id": f"ensemble_{index + 1}",
                            "candidate_character_ids": list(slot.candidate_card_ids),
                        }
                        for index, slot in enumerate(recipe.cast_slots)
                    ],
                }
            )
        return {
            "default_case_id": DEFAULT_CASE_ID,
            "default_location_id": DEFAULT_LOCATION_ID,
            "default_recipe_id": DEFAULT_RECIPE_ID,
            "generation": {
                "provider": "openrouter",
                "provider_required": True,
                "cast_size": 8,
                "character_pool_size": len(list_content_ids(CHARACTER_CARDS_DIR)),
            },
            "recipes": recipes,
            "locations": [self._location_summary(location)],
            "characters": [
                self._character_summary(character_id)
                for character_id in list_content_ids(CHARACTER_CARDS_DIR)
            ],
        }

    def bootstrap(self) -> dict[str, object]:
        return {
            "catalog": self.catalog(),
            "game": self.engine.view() if self.engine else None,
            "recipe": self.recipe_metadata(),
            "generation": self.generation_metadata(),
        }

    def generation_metadata(self) -> dict[str, object] | None:
        if self.engine is None or self._generation_metadata is None:
            return None
        return dict(self._generation_metadata)

    def recipe_metadata(self) -> dict[str, object] | None:
        """Return reproducibility metadata without exposing the selected spine."""

        if self.engine is None or self.engine.recipe_selection is None:
            return None
        selection = self.engine.recipe_selection
        return {
            "recipe_id": selection.recipe_id,
            "schema_version": selection.schema_version,
            "seed": selection.seed,
            "cast_mode": selection.cast_mode,
            "story_source": self.engine.story_presentation.source,
            "story_status": "ready",
        }

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
        replay_envelope = snapshot_engine(engine)
        confirmed_contradictions = sorted(
            contradiction.id
            for contradiction in engine.runtime.player_knowledge.contradictions
            if contradiction.confirmed
        )
        audit = {
            "canonical_truth": {
                "case_id": case.id,
                "seed": case.seed,
                "location_id": case.location_package_id,
                "cast_ids": list(case.character_ids),
                "victim_id": case.murder.victim_id,
                "culprit_id": case.murder.murderer_id,
                "method": case.murder.method,
                "means": case.murder.means,
                "motive": case.murder.motive,
                "opportunity": case.murder.opportunity,
                "evidence_routes": [
                    route.model_dump(mode="json")
                    for route in solution.evidence_routes
                ],
                "case_document": case.model_dump(mode="json"),
            },
            "npc_action_trace": [
                {
                    "turn": entry.turn,
                    "actor_id": entry.actor_id,
                    "proposal": entry.proposed_action_id,
                    "resolved_action_id": entry.resolved_action_id,
                    "kind": entry.action_kind,
                    "source": entry.source,
                    "outcome": entry.outcome,
                    "reason": entry.reason,
                    "room_before_id": entry.room_before_id,
                    "room_after_id": entry.room_after_id,
                    "target_character_id": entry.target_character_id,
                    "evidence_id": entry.evidence_id,
                    "event_id": entry.event_id,
                    "knowledge_delta": {
                        "fact_ids_gained": list(entry.learned_fact_ids),
                        "fact_ids_shared": list(entry.disclosed_fact_ids),
                        "evidence_ids_gained": list(entry.learned_evidence_ids),
                    },
                    "participant_knowledge_deltas": [
                        delta.model_dump(mode="json")
                        for delta in entry.participant_knowledge_deltas
                    ],
                    "evidence_condition_before": (
                        entry.evidence_condition_before.value
                        if entry.evidence_condition_before is not None
                        else None
                    ),
                    "evidence_condition_after": (
                        entry.evidence_condition_after.value
                        if entry.evidence_condition_after is not None
                        else None
                    ),
                }
                for entry in engine.runtime.npc_action_audit
            ],
            "final_knowledge": {
                "player": {
                    "known_fact_ids": sorted(
                        engine.runtime.player_knowledge.known_fact_ids
                    ),
                    "discovered_evidence_ids": sorted(
                        engine.runtime.player_knowledge.discovered_evidence_ids
                    ),
                    "statement_ids": [
                        statement.id
                        for statement in engine.runtime.player_knowledge.statements
                    ],
                    "confirmed_contradiction_ids": confirmed_contradictions,
                },
                "npcs": {
                    character_id: {
                        "alive": state.alive,
                        "known_fact_ids": sorted(state.known_fact_ids),
                        "known_evidence_ids": sorted(state.known_evidence_ids),
                        "beliefs": {
                            subject_id: belief.model_dump(mode="json")
                            for subject_id, belief in state.beliefs.items()
                        },
                        "intentions": list(state.intentions),
                        "conversation_memory": [
                            memory.model_dump(mode="json")
                            for memory in state.conversation_memory
                        ],
                        "private_overlay": case.overlays[
                            character_id
                        ].model_dump(mode="json"),
                    }
                    for character_id, state in engine.runtime.characters.items()
                },
            },
            "replay_verification": {
                "verified": replay_envelope.runtime == engine.runtime,
                "action_count": len(engine.action_history or []),
                "resolved_npc_action_count": len(
                    engine.runtime.npc_action_audit
                ),
            },
        }
        return {
            "case_title": engine.view().case_title,
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
                "evidence_routes": [
                    route.model_dump(mode="json")
                    for route in solution.evidence_routes
                ],
            },
            "audit": audit,
        }

    def _require_engine(self) -> GameEngine:
        if self.engine is None:
            raise ValueError("No active game.")
        return self.engine

    @staticmethod
    def _display_name(character_id: str) -> str:
        try:
            return load_character_card(character_id).data.name
        except (OSError, ValueError):
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


__all__ = [
    "DEFAULT_CASE_ID",
    "DEFAULT_LOCATION_ID",
    "DEFAULT_RECIPE_ID",
    "GameService",
    "SaveValidationError",
]
