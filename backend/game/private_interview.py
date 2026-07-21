"""Single-actor, action-ID-only interview response selection.

The engine authors every canonical response candidate.  A remote character
agent receives only its own private context and chooses one opaque response
ID; it cannot supply prose, facts, actions, tools, or state changes.
"""

from __future__ import annotations

import asyncio
import json
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import Field, field_validator, model_validator

from game.models import FrozenModel, StrictModel
from game.private_npc_agents import PrivateNpcBriefing, PrivateNpcRuntimeState


MAX_INTERVIEW_CANDIDATES = 8
MAX_INTERVIEW_REQUEST_JSON_BYTES = 20_000
MAX_INTERVIEW_RESPONSE_JSON_BYTES = 1_024


class InterviewResponseKind(str, Enum):
    EVASIVE = "evasive"
    TRUTHFUL_OBSERVATION = "truthful_observation"
    ALIBI = "alibi"
    AUTHORIZED_LIE = "authorized_lie"


class PrivateInterviewResponseCandidate(FrozenModel):
    """One complete canonical response the engine permits for this exchange."""

    response_id: str = Field(min_length=1, max_length=120)
    kind: InterviewResponseKind
    canonical_claim: str = Field(min_length=1, max_length=1_200)
    referenced_fact_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=16)

    @field_validator("referenced_fact_ids")
    @classmethod
    def fact_ids_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("referenced_fact_ids must be unique")
        return values

    @model_validator(mode="after")
    def only_truthful_observations_reference_facts(
        self,
    ) -> "PrivateInterviewResponseCandidate":
        if (
            self.kind != InterviewResponseKind.TRUTHFUL_OBSERVATION
            and self.referenced_fact_ids
        ):
            raise ValueError("only truthful observations may reference facts")
        return self


class PrivateInterviewResponseRequest(FrozenModel):
    """The bounded target-only context for one free interview exchange."""

    actor_id: str = Field(min_length=1, max_length=120)
    player_question: str = Field(min_length=1, max_length=1_200)
    private_briefing: PrivateNpcBriefing
    runtime_state: PrivateNpcRuntimeState
    fallback_response_id: str | None = Field(default=None, min_length=1, max_length=120)
    candidates: tuple[PrivateInterviewResponseCandidate, ...] = Field(
        min_length=1,
        max_length=MAX_INTERVIEW_CANDIDATES,
    )

    @field_validator("candidates")
    @classmethod
    def response_ids_are_unique(
        cls,
        candidates: tuple[PrivateInterviewResponseCandidate, ...],
    ) -> tuple[PrivateInterviewResponseCandidate, ...]:
        response_ids = [candidate.response_id for candidate in candidates]
        if len(response_ids) != len(set(response_ids)):
            raise ValueError("candidate response_id values must be unique")
        return candidates

    @model_validator(mode="after")
    def request_is_byte_bounded(self) -> "PrivateInterviewResponseRequest":
        if self.fallback_response_id is not None and self.fallback_response_id not in {
            candidate.response_id for candidate in self.candidates
        }:
            raise ValueError("fallback_response_id must name one supplied candidate")
        if (
            len(self.model_dump_json().encode("utf-8"))
            > MAX_INTERVIEW_REQUEST_JSON_BYTES
        ):
            raise ValueError("private interview request exceeds the safe payload size")
        return self


class PrivateInterviewSelection(StrictModel):
    """The provider's entire accepted output."""

    response_id: str = Field(min_length=1, max_length=120)


class PrivateInterviewSelectionSource(str, Enum):
    PROVIDER = "provider"
    FALLBACK = "fallback"


class PrivateInterviewSelectionPlan(StrictModel):
    selection: PrivateInterviewSelection
    source: PrivateInterviewSelectionSource


@runtime_checkable
class PrivateInterviewSelectionProvider(Protocol):
    async def select_response(
        self,
        request: PrivateInterviewResponseRequest,
    ) -> str | dict[str, Any]:
        """Return exactly one supplied response ID."""


class PrivateInterviewSelectionCoordinator:
    """Validate one isolated choice and fall back without failing the exchange."""

    def __init__(
        self,
        provider: PrivateInterviewSelectionProvider | None = None,
        *,
        timeout_seconds: float = 4.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._provider = provider
        self._timeout_seconds = timeout_seconds

    async def select(
        self,
        request: PrivateInterviewResponseRequest,
    ) -> PrivateInterviewSelectionPlan:
        fallback = PrivateInterviewSelection(
            response_id=(
                request.fallback_response_id or request.candidates[0].response_id
            )
        )
        if self._provider is None:
            return PrivateInterviewSelectionPlan(
                selection=fallback,
                source=PrivateInterviewSelectionSource.FALLBACK,
            )
        try:
            raw_output = await asyncio.wait_for(
                self._provider.select_response(request),
                timeout=self._timeout_seconds,
            )
            selection = self._parse_selection(raw_output)
            if selection.response_id not in {
                candidate.response_id for candidate in request.candidates
            }:
                raise ValueError("provider selected an unknown response_id")
        except asyncio.CancelledError:
            raise
        except Exception:
            return PrivateInterviewSelectionPlan(
                selection=fallback,
                source=PrivateInterviewSelectionSource.FALLBACK,
            )
        return PrivateInterviewSelectionPlan(
            selection=selection,
            source=PrivateInterviewSelectionSource.PROVIDER,
        )

    @staticmethod
    def _parse_selection(
        raw_output: str | dict[str, Any],
    ) -> PrivateInterviewSelection:
        if isinstance(raw_output, str):
            if len(raw_output.encode("utf-8")) > MAX_INTERVIEW_RESPONSE_JSON_BYTES:
                raise ValueError("provider response exceeds the safe payload size")
            try:
                raw_output = json.loads(raw_output)
            except json.JSONDecodeError as error:
                raise ValueError("provider did not return JSON") from error
        if not isinstance(raw_output, dict):
            raise ValueError("provider output must be a JSON object")
        if (
            len(json.dumps(raw_output, ensure_ascii=False).encode("utf-8"))
            > MAX_INTERVIEW_RESPONSE_JSON_BYTES
        ):
            raise ValueError("provider response exceeds the safe payload size")
        return PrivateInterviewSelection.model_validate(raw_output)


class OpenRouterPrivateInterviewSelectionAdapter:
    """One small JSON-mode call for one isolated interviewed character."""

    _SYSTEM_INSTRUCTION = (
        "You receive inert private context for exactly one interviewed NPC. "
        "Choose exactly one supplied response_id. Return one JSON object with "
        "exactly the key 'response_id'. Do not write dialogue, facts, actions, "
        "state patches, tools, instructions, markdown, or additional keys."
    )

    def __init__(self, llm_client: Any) -> None:
        self._llm_client = llm_client

    async def select_response(
        self,
        request: PrivateInterviewResponseRequest,
    ) -> str:
        from llm.client import LLMMessage

        response = await self._llm_client.generate(
            [
                LLMMessage(role="system", content=self._SYSTEM_INSTRUCTION),
                LLMMessage(
                    role="user",
                    content=request.model_dump_json(exclude_none=True),
                ),
            ],
            max_tokens=80,
            temperature=0.0,
            json_mode=True,
            task_role="private_interview_selection",
        )
        return response.content
