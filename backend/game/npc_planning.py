"""Constrained, non-authoritative NPC intent batch planning.

This boundary is deliberately narrower than the deterministic turn engine.  A
caller supplies a frozen, player-safe snapshot and the finite action IDs that
each actor may choose from.  A provider may select exactly one of those IDs
per actor, but it can never send dialogue, tool parameters, state patches, or
new world facts.  Invalid or unavailable provider output degrades to the
deterministic first candidate for each actor.
"""

from __future__ import annotations

import asyncio
import json
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import Field, field_validator, model_validator

from game.models import FrozenModel, StrictModel


MAX_NPC_ACTORS = 20
MAX_CANDIDATES_PER_ACTOR = 12
MAX_SNAPSHOT_EVENTS = 24
MAX_REQUEST_JSON_BYTES = 24_000
MAX_PROVIDER_JSON_BYTES = 8_000


class NpcActionCandidate(FrozenModel):
    """One engine-authored action option, identified only by a stable ID."""

    action_id: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=360)


class NpcActorActionOptions(FrozenModel):
    """The complete candidate set available to one NPC in this turn."""

    actor_id: str = Field(min_length=1, max_length=120)
    candidates: tuple[NpcActionCandidate, ...] = Field(
        min_length=1, max_length=MAX_CANDIDATES_PER_ACTOR
    )

    @field_validator("candidates")
    @classmethod
    def candidate_ids_are_unique(
        cls, candidates: tuple[NpcActionCandidate, ...]
    ) -> tuple[NpcActionCandidate, ...]:
        action_ids = [candidate.action_id for candidate in candidates]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("candidate action_id values must be unique")
        return candidates


class SafeNpcTurnSnapshot(FrozenModel):
    """Small, immutable data explicitly cleared for this planning request.

    It intentionally contains no authored card text, hidden relationships,
    schedules, evidence locations, player knowledge, or runtime state patch.
    The caller may only provide a concise public scene summary and already
    public event summaries.
    """

    turn_number: int = Field(ge=0, le=10_000)
    phase: str = Field(min_length=1, max_length=80)
    public_scene_summary: str = Field(min_length=1, max_length=1_200)
    public_event_summaries: tuple[str, ...] = Field(
        default_factory=tuple, max_length=MAX_SNAPSHOT_EVENTS
    )

    @field_validator("public_event_summaries")
    @classmethod
    def event_summaries_are_bounded(
        cls, summaries: tuple[str, ...]
    ) -> tuple[str, ...]:
        if any(not 1 <= len(summary) <= 360 for summary in summaries):
            raise ValueError("each public event summary must be 1..360 characters")
        return summaries


class NpcIntentPlanningRequest(FrozenModel):
    """The entire provider input for one immutable turn-start snapshot."""

    snapshot: SafeNpcTurnSnapshot
    actor_options: tuple[NpcActorActionOptions, ...] = Field(
        min_length=1, max_length=MAX_NPC_ACTORS
    )

    @field_validator("actor_options")
    @classmethod
    def actor_ids_are_unique(
        cls, options: tuple[NpcActorActionOptions, ...]
    ) -> tuple[NpcActorActionOptions, ...]:
        actor_ids = [option.actor_id for option in options]
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("actor_options must not contain duplicate actor_id values")
        return options

    @model_validator(mode="after")
    def request_size_is_bounded(self) -> "NpcIntentPlanningRequest":
        payload_size = len(self.model_dump_json().encode("utf-8"))
        if payload_size > MAX_REQUEST_JSON_BYTES:
            raise ValueError("planning request exceeds the safe payload size")
        return self


class ProviderNpcIntentSelection(StrictModel):
    """A provider may return only an actor ID and a candidate action ID."""

    actor_id: str = Field(min_length=1, max_length=120)
    action_id: str = Field(min_length=1, max_length=120)


class ProviderNpcIntentBatch(StrictModel):
    """Strict provider response envelope; no patches, dialogue, or tools."""

    selections: tuple[ProviderNpcIntentSelection, ...] = Field(
        min_length=1, max_length=MAX_NPC_ACTORS
    )


class NpcPlanningSource(str, Enum):
    PROVIDER = "provider"
    FALLBACK = "fallback"


class NpcIntentPlan(StrictModel):
    """A validated selection set ready for a deterministic engine to map."""

    selections: tuple[ProviderNpcIntentSelection, ...]
    source: NpcPlanningSource


@runtime_checkable
class NpcIntentBatchProvider(Protocol):
    """Provider-neutral interface for one batch planning call per turn."""

    async def plan_intents(self, request: NpcIntentPlanningRequest) -> str | dict[str, Any]:
        """Return JSON/object data matching :class:`ProviderNpcIntentBatch`."""


class DeterministicNpcIntentFallback:
    """Always choose each actor's first engine-authored candidate."""

    def plan(self, request: NpcIntentPlanningRequest) -> NpcIntentPlan:
        return NpcIntentPlan(
            selections=tuple(
                ProviderNpcIntentSelection(
                    actor_id=option.actor_id, action_id=option.candidates[0].action_id
                )
                for option in request.actor_options
            ),
            source=NpcPlanningSource.FALLBACK,
        )


class ConstrainedNpcIntentPlanningCoordinator:
    """Accept only complete, finite provider choices; otherwise fall back."""

    def __init__(
        self,
        provider: NpcIntentBatchProvider | None = None,
        *,
        timeout_seconds: float = 4.0,
        fallback: DeterministicNpcIntentFallback | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._fallback = fallback or DeterministicNpcIntentFallback()

    async def plan(self, request: NpcIntentPlanningRequest) -> NpcIntentPlan:
        """Make at most one provider call for this immutable request."""
        if self._provider is None:
            return self._fallback.plan(request)

        try:
            raw_output = await asyncio.wait_for(
                self._provider.plan_intents(request), timeout=self._timeout_seconds
            )
            provider_output = self._parse_provider_output(raw_output)
            self._validate_complete_selection(provider_output, request)
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._fallback.plan(request)

        return NpcIntentPlan(
            selections=provider_output.selections,
            source=NpcPlanningSource.PROVIDER,
        )

    @staticmethod
    def _parse_provider_output(raw_output: str | dict[str, Any]) -> ProviderNpcIntentBatch:
        if isinstance(raw_output, str):
            if len(raw_output.encode("utf-8")) > MAX_PROVIDER_JSON_BYTES:
                raise ValueError("provider response exceeds safe payload size")
            try:
                raw_output = json.loads(raw_output)
            except json.JSONDecodeError as exc:
                raise ValueError("provider did not return JSON") from exc
        if not isinstance(raw_output, dict):
            raise ValueError("provider output must be a JSON object")
        if len(json.dumps(raw_output, ensure_ascii=False).encode("utf-8")) > MAX_PROVIDER_JSON_BYTES:
            raise ValueError("provider response exceeds safe payload size")
        return ProviderNpcIntentBatch.model_validate(raw_output)

    @staticmethod
    def _validate_complete_selection(
        output: ProviderNpcIntentBatch, request: NpcIntentPlanningRequest
    ) -> None:
        expected = {option.actor_id: {candidate.action_id for candidate in option.candidates}
                    for option in request.actor_options}
        selected_actors = [selection.actor_id for selection in output.selections]
        if len(selected_actors) != len(set(selected_actors)):
            raise ValueError("provider selected an actor more than once")
        if set(selected_actors) != set(expected):
            raise ValueError("provider selections must cover exactly the requested actors")
        for selection in output.selections:
            if selection.action_id not in expected[selection.actor_id]:
                raise ValueError("provider chose an action outside the candidate set")


class OpenRouterNpcIntentBatchAdapter:
    """OpenRouter adapter that forwards only the constrained request JSON."""

    _SYSTEM_INSTRUCTION = (
        "Choose exactly one action_id for every supplied actor. Return one JSON "
        "object with exactly the key 'selections', containing objects with exactly "
        "the keys 'actor_id' and 'action_id'. Choose only supplied action IDs. Do "
        "not write dialogue, facts, state patches, tool calls, or markdown."
    )

    def __init__(self, llm_client: Any) -> None:
        self._llm_client = llm_client

    async def plan_intents(self, request: NpcIntentPlanningRequest) -> str:
        from llm.client import LLMMessage

        response = await self._llm_client.generate(
            [
                LLMMessage(role="system", content=self._SYSTEM_INSTRUCTION),
                LLMMessage(
                    role="user",
                    content=request.model_dump_json(exclude_none=True),
                ),
            ],
            max_tokens=320,
            temperature=0.0,
            json_mode=True,
        )
        return response.content
