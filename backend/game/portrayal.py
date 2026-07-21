"""Constrained, non-authoritative NPC dialogue portrayal.

This module is intentionally isolated from the game engine.  It may turn a
claim the engine has *already* decided is permissible into natural dialogue,
but it can neither discover facts nor request a state change.  A caller must
continue to use ``PortrayalResult.canonical_claim`` as the authoritative
record; the surface utterance is presentation only.
"""

from __future__ import annotations

import asyncio
import json
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import Field, field_validator

from game.models import StrictModel


MAX_PROVIDER_UTTERANCE_CHARS = 600


class PermittedFact(StrictModel):
    """A fact statement explicitly cleared for this one portrayal request."""

    id: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=1_200)


class PublicDialogueLine(StrictModel):
    """A previously spoken line that is safe to include in a prompt."""

    speaker_name: str = Field(min_length=1, max_length=120)
    utterance: str = Field(min_length=1, max_length=1_000)


class PortrayalRequest(StrictModel):
    """The complete, deliberately narrow input boundary for dialogue rendering.

    This model has no card, case, schedule, relationship, world, or action
    fields.  ``canonical_claim`` and ``permitted_facts`` are supplied by an
    authoritative rules layer after its own disclosure checks.
    """

    character_id: str = Field(min_length=1, max_length=120)
    character_name: str = Field(min_length=1, max_length=120)
    speaking_style: str = Field(min_length=1, max_length=500)
    emotional_state: str = Field(min_length=1, max_length=240)
    player_question: str = Field(min_length=1, max_length=1_200)
    canonical_claim: str = Field(min_length=1, max_length=1_200)
    permitted_facts: tuple[PermittedFact, ...] = Field(default_factory=tuple, max_length=40)
    prior_public_dialogue: tuple[PublicDialogueLine, ...] = Field(
        default_factory=tuple, max_length=16
    )

    @field_validator("permitted_facts")
    @classmethod
    def permitted_fact_ids_are_unique(
        cls, facts: tuple[PermittedFact, ...]
    ) -> tuple[PermittedFact, ...]:
        ids = [fact.id for fact in facts]
        if len(ids) != len(set(ids)):
            raise ValueError("permitted_facts must not contain duplicate ids")
        return facts


class ProviderPortrayal(StrictModel):
    """The only structured response accepted from a remote provider."""

    utterance: str = Field(min_length=1, max_length=MAX_PROVIDER_UTTERANCE_CHARS)
    referenced_fact_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=16)

    @field_validator("referenced_fact_ids")
    @classmethod
    def references_are_unique(
        cls, fact_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("referenced_fact_ids must not contain duplicates")
        return fact_ids


class PortrayalSource(str, Enum):
    PROVIDER = "provider"
    FALLBACK = "fallback"


class PortrayalResult(StrictModel):
    """Presentation data with a separate canonical engine claim.

    ``surface_utterance`` is never evidence that a fact is true.  It is merely
    a character's rendering of the canonical claim selected by the rules
    layer.  The result intentionally contains no action or world patch.
    """

    canonical_claim: str
    surface_utterance: str | None = None
    source: PortrayalSource
    referenced_fact_ids: tuple[str, ...] = Field(default_factory=tuple)


@runtime_checkable
class PortrayalProvider(Protocol):
    """Provider-neutral boundary for a structured dialogue renderer."""

    async def portray(self, request: PortrayalRequest) -> str | dict[str, Any]:
        """Return only JSON/object data matching :class:`ProviderPortrayal`."""


class DeterministicPortrayalFallback:
    """Safe local renderer used whenever no valid provider response exists."""

    def portray(self, request: PortrayalRequest) -> PortrayalResult:
        # Repeating the authorised claim is deliberately unglamorous but makes
        # outages incapable of changing the game's facts or advancing a turn.
        return PortrayalResult(
            canonical_claim=request.canonical_claim,
            surface_utterance=request.canonical_claim,
            source=PortrayalSource.FALLBACK,
        )


class ConstrainedPortrayalCoordinator:
    """Validate remote dialogue strictly and degrade safely on every failure."""

    def __init__(
        self,
        provider: PortrayalProvider | None = None,
        *,
        timeout_seconds: float = 4.0,
        fallback: DeterministicPortrayalFallback | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._fallback = fallback or DeterministicPortrayalFallback()

    async def portray(self, request: PortrayalRequest) -> PortrayalResult:
        """Render a claim, never letting remote output affect world truth."""
        if self._provider is None:
            return self._fallback.portray(request)

        try:
            raw_output = await asyncio.wait_for(
                self._provider.portray(request), timeout=self._timeout_seconds
            )
            provider_output = self._parse_provider_output(raw_output)
            self._validate_references(provider_output, request)
        except asyncio.CancelledError:
            # A cancellation should not be swallowed: callers use it to end a
            # request scope.  Every other provider/validation failure is safe.
            raise
        except Exception:
            return self._fallback.portray(request)

        return PortrayalResult(
            canonical_claim=request.canonical_claim,
            surface_utterance=provider_output.utterance,
            source=PortrayalSource.PROVIDER,
            referenced_fact_ids=provider_output.referenced_fact_ids,
        )

    @staticmethod
    def _parse_provider_output(raw_output: str | dict[str, Any]) -> ProviderPortrayal:
        if isinstance(raw_output, str):
            try:
                raw_output = json.loads(raw_output)
            except json.JSONDecodeError as exc:
                raise ValueError("provider did not return JSON") from exc
        if not isinstance(raw_output, dict):
            raise ValueError("provider output must be a JSON object")
        return ProviderPortrayal.model_validate(raw_output)

    @staticmethod
    def _validate_references(
        output: ProviderPortrayal, request: PortrayalRequest
    ) -> None:
        permitted_ids = {fact.id for fact in request.permitted_facts}
        unknown_ids = set(output.referenced_fact_ids).difference(permitted_ids)
        if unknown_ids:
            raise ValueError("provider cited a fact that was not permitted")


class OpenRouterPortrayalAdapter:
    """Small adapter for the existing OpenRouter ``LLMClient.generate`` API.

    Its prompt is built exclusively from ``PortrayalRequest``.  In particular,
    it does not accept or forward character-card prompts, provider system
    prompts, secret case data, actions, tools, or mutable world state.
    """

    _SYSTEM_INSTRUCTION = (
        "Render dialogue only. Return one JSON object with exactly the keys "
        "'utterance' and 'referenced_fact_ids'. The utterance must answer in "
        "character voice using only the supplied canonical claim and permitted "
        "facts. Do not invent facts, issue actions, describe world changes, or "
        "include markdown."
    )

    def __init__(self, llm_client: Any) -> None:
        self._llm_client = llm_client

    async def portray(self, request: PortrayalRequest) -> str:
        # Delayed import keeps this domain boundary usable without configuring
        # OpenRouter and avoids importing any historical prompt-building layer.
        from llm.client import LLMMessage

        safe_payload = {
            "character": {
                "id": request.character_id,
                "name": request.character_name,
                "speaking_style": request.speaking_style,
                "emotional_state": request.emotional_state,
            },
            "player_question": request.player_question,
            "canonical_claim": request.canonical_claim,
            "permitted_facts": [fact.model_dump() for fact in request.permitted_facts],
            "prior_public_dialogue": [
                line.model_dump() for line in request.prior_public_dialogue
            ],
        }
        response = await self._llm_client.generate(
            [
                LLMMessage(role="system", content=self._SYSTEM_INSTRUCTION),
                LLMMessage(
                    role="user",
                    content=json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":")),
                ),
            ],
            max_tokens=220,
            temperature=0.2,
            json_mode=True,
            task_role="portrayal",
        )
        return response.content
