"""Red-first contracts for isolated, engine-authored interview choices.

These tests deliberately describe a new boundary.  The remote selector may
choose one response ID for the NPC being interviewed, but it must never author
dialogue, facts, or state changes.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from conftest import make_dummy_generated_document
from game.actions import AdvanceOpeningIntent, BeginInterviewIntent, InterviewExchangeIntent
from game.case_generation import compile_generated_scenario
from game.content import load_case, load_location
from game.engine import GameEngine
from game.models import CaseDefinition
from game.persistence import restore_engine, snapshot_engine
from game.service import GameService
from game.private_interview import (
    PrivateInterviewResponseCandidate,
    PrivateInterviewResponseRequest,
    PrivateInterviewSelection,
    PrivateInterviewSelectionCoordinator,
    PrivateInterviewSelectionSource,
)
from game.private_npc_agents import (
    PrivateNpcBriefing,
    PrivateNpcFact,
    PrivateNpcRuntimeState,
)


def _request(*, fallback_response_id: str | None = None) -> PrivateInterviewResponseRequest:
    return PrivateInterviewResponseRequest(
        actor_id="edgar_blackwood",
        player_question="Where were you when the lights failed?",
        private_briefing=PrivateNpcBriefing(
            character_summary="Edgar has a private motive.",
            private_facts=(PrivateNpcFact(id="edgar-private", statement="Keep this private."),),
        ),
        runtime_state=PrivateNpcRuntimeState(state_summary="Guarded.", urgency=4),
        fallback_response_id=fallback_response_id,
        candidates=(
            PrivateInterviewResponseCandidate(
                response_id="evasive",
                kind="evasive",
                canonical_claim="I have nothing further to add.",
            ),
            PrivateInterviewResponseCandidate(
                response_id="observation_0",
                kind="truthful_observation",
                canonical_claim="I saw the clock stop.",
                referenced_fact_ids=("fact_clock",),
            ),
            PrivateInterviewResponseCandidate(
                response_id="alibi",
                kind="alibi",
                canonical_claim="I was in the library.",
            ),
            PrivateInterviewResponseCandidate(
                response_id="lie_0",
                kind="authorized_lie",
                canonical_claim="I never entered the study.",
            ),
        ),
    )


class _Provider:
    def __init__(self, output: object) -> None:
        self.output = output

    async def select_response(self, request: PrivateInterviewResponseRequest) -> object:
        return self.output


@pytest.mark.parametrize(
    "output",
    (
        {"response_id": "lie_0", "claim": "new fact"},
        {"response_id": "lie_0", "state_patch": {"turn": 99}},
        {"response_id": "not-an-authored-choice"},
        "not JSON",
    ),
)
def test_interview_selector_accepts_only_one_authored_id_and_other_output_falls_back(output: object) -> None:
    request = _request()
    valid = asyncio.run(
        PrivateInterviewSelectionCoordinator(_Provider({"response_id": "lie_0"})).select(request)
    )
    assert valid.selection == PrivateInterviewSelection(response_id="lie_0")
    assert valid.source is PrivateInterviewSelectionSource.PROVIDER

    fallback = asyncio.run(PrivateInterviewSelectionCoordinator(_Provider(output)).select(request))
    assert fallback.selection.response_id == "evasive"
    assert fallback.source is PrivateInterviewSelectionSource.FALLBACK


def test_interview_selector_propagates_cancellation() -> None:
    class BlockingProvider:
        async def select_response(self, request: PrivateInterviewResponseRequest) -> object:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    async def scenario() -> None:
        task = asyncio.create_task(
            PrivateInterviewSelectionCoordinator(BlockingProvider()).select(_request())
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_interview_selector_uses_the_engine_chosen_useful_fallback() -> None:
    request = _request(fallback_response_id="alibi")

    plan = asyncio.run(
        PrivateInterviewSelectionCoordinator(_Provider("not JSON")).select(request)
    )

    assert plan.selection.response_id == "alibi"
    assert plan.source is PrivateInterviewSelectionSource.FALLBACK


def test_interview_request_rejects_a_forged_fallback_id() -> None:
    with pytest.raises(
        ValueError,
        match="fallback_response_id must name one supplied candidate",
    ):
        _request(fallback_response_id="forged")


def test_interview_response_metadata_on_another_action_is_rejected_atomically() -> None:
    engine = _generated_engine()
    runtime_before = engine.runtime.model_copy(deep=True)
    history_before = list(engine.action_history)

    with pytest.raises(
        ValueError,
        match="interview_response_id is valid only for interview exchanges",
    ):
        engine.apply(
            AdvanceOpeningIntent(),
            interview_response_id="forged-response-id",
        )

    assert engine.runtime == runtime_before
    assert engine.action_history == history_before


def test_response_id_cannot_be_combined_with_legacy_interview_rules() -> None:
    engine = _generated_engine()
    actor_id = _interviewable_actor_with_all_choice_kinds(engine)
    _begin(engine, actor_id)
    runtime_before = engine.runtime.model_copy(deep=True)
    history_before = list(engine.action_history)

    with pytest.raises(
        ValueError,
        match="legacy interview rules cannot contain a response ID",
    ):
        engine.apply(
            InterviewExchangeIntent(message="Tell me what happened."),
            interview_response_id="forged-response-id",
            interview_rules_version=1,
        )

    assert engine.runtime == runtime_before
    assert engine.action_history == history_before


def _generated_engine() -> GameEngine:
    source = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    generated = compile_generated_scenario(
        make_dummy_generated_document(),
        character_ids=source.character_ids,
        location=location,
        seed=84,
    )
    return GameEngine(generated.case, location, story_presentation=generated.presentation)


def _interviewable_actor_with_all_choice_kinds(engine: GameEngine) -> str:
    return next(
        character_id
        for character_id, overlay in engine.case.overlays.items()
        if overlay.lies
        and any(
            set(observation.fact_ids).isdisjoint(overlay.hides_fact_ids)
            for observation in overlay.observations
        )
    )


def _begin(engine: GameEngine, actor_id: str) -> None:
    engine.apply(AdvanceOpeningIntent())
    engine.runtime.player_room_id = engine.runtime.characters[actor_id].current_room_id
    assert engine.apply(BeginInterviewIntent(character_id=actor_id)).accepted


def test_generated_interview_preview_contains_one_bounded_target_only_request() -> None:
    engine = _generated_engine()
    actor_id = _interviewable_actor_with_all_choice_kinds(engine)
    _begin(engine, actor_id)

    preview = engine.preview(InterviewExchangeIntent(message="What did you see?"))
    request = preview.private_interview_request
    assert request is not None
    assert request.actor_id == actor_id
    assert request.player_question == "What did you see?"
    assert 1 <= len(request.candidates) <= 8
    assert {candidate.kind for candidate in request.candidates} >= {
        "truthful_observation", "alibi", "authorized_lie", "evasive"
    }
    assert all(candidate.canonical_claim for candidate in request.candidates)
    assert all(
        candidate.kind == "truthful_observation" or not candidate.referenced_fact_ids
        for candidate in request.candidates
    )

    serialized = request.model_dump_json()
    if actor_id != engine.case.murder.murderer_id:
        assert "host_murder_truth" not in serialized
    for other_id, overlay in engine.case.overlays.items():
        if other_id == actor_id:
            continue
        assert overlay.private_motive not in serialized
        for secret in overlay.secrets:
            assert secret not in serialized


def test_murderer_selector_knows_the_crime_but_cannot_choose_a_hidden_confession() -> None:
    engine = _generated_engine()
    murderer_id = engine.case.murder.murderer_id
    _begin(engine, murderer_id)

    request = engine.preview(
        InterviewExchangeIntent(message="Did you kill the victim?")
    ).private_interview_request

    assert request is not None
    assert request.private_briefing.private_facts[0].id == "host_murder_truth"
    hidden_fact_ids = set(engine.case.overlays[murderer_id].hides_fact_ids)
    hidden_claims = {
        observation.summary
        for observation in engine.case.overlays[murderer_id].observations
        if set(observation.fact_ids) & hidden_fact_ids
    }
    assert all(
        not set(candidate.referenced_fact_ids) & hidden_fact_ids
        and candidate.canonical_claim not in hidden_claims
        for candidate in request.candidates
    )


def test_generated_murderer_freeform_alibi_and_lies_never_become_candidates() -> None:
    source = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    document = make_dummy_generated_document()
    murderer_id = document["case"]["murder"]["murderer_id"]  # type: ignore[index]
    overlay = document["case"]["overlays"][murderer_id]  # type: ignore[index]
    unsafe_alibi = "The death was my doing, just as the stopped clock proves."
    unsafe_lie = "Only I know why the fireplace poker was returned."
    overlay["alibi_claim"] = unsafe_alibi
    overlay["alibi_disclosed_fact_ids"] = []
    overlay["lies"][0]["claim"] = unsafe_lie
    overlay["lies"][0]["disclosed_fact_ids"] = []
    generated = compile_generated_scenario(
        document,
        character_ids=source.character_ids,
        location=location,
        seed=84,
    )
    engine = GameEngine(
        generated.case,
        location,
        story_presentation=generated.presentation,
    )
    _begin(engine, murderer_id)

    request = engine.preview(
        InterviewExchangeIntent(message="Tell me what really happened.")
    ).private_interview_request

    assert request is not None
    claims = {candidate.canonical_claim for candidate in request.candidates}
    assert unsafe_alibi not in claims
    assert unsafe_lie not in claims
    assert {candidate.kind for candidate in request.candidates} >= {
        "alibi",
        "authorized_lie",
        "evasive",
    }


def test_new_exchange_after_generated_v2_restore_uses_hardened_rules() -> None:
    source = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    document = make_dummy_generated_document()
    murderer_id = document["case"]["murder"]["murderer_id"]  # type: ignore[index]
    overlay = document["case"]["overlays"][murderer_id]  # type: ignore[index]
    unsafe_alibi = "The death was my doing, just as the stopped clock proves."
    unsafe_lie = "Only I know why the fireplace poker was returned."
    overlay["alibi_claim"] = unsafe_alibi
    overlay["alibi_disclosed_fact_ids"] = []
    overlay["lies"][0]["claim"] = unsafe_lie
    overlay["lies"][0]["disclosed_fact_ids"] = []
    generated = compile_generated_scenario(
        document,
        character_ids=source.character_ids,
        location=location,
        seed=84,
    )
    case = CaseDefinition.model_validate(
        {
            **generated.case.model_dump(mode="json"),
            "initial_player_room_id": generated.case.opening.post_meeting_room_ids[
                murderer_id
            ],
        }
    )
    engine = GameEngine(case, location)
    engine.apply(AdvanceOpeningIntent())
    assert engine.apply(BeginInterviewIntent(character_id=murderer_id)).accepted
    assert engine.apply(
        InterviewExchangeIntent(message="Where were you?"),
        interview_rules_version=1,
    ).accepted
    assert engine.runtime.player_knowledge.statements[-1].claim == unsafe_alibi
    old_v2 = snapshot_engine(engine).model_dump(mode="json")
    old_v2["schema_version"] = 2
    for entry in old_v2["action_history"]:
        entry.pop("interview_rules_version", None)
        entry.pop("location_event_rules_version", None)

    restored = restore_engine(old_v2, case, location)
    command = InterviewExchangeIntent(message="What are you hiding?")
    request = restored.preview(command).private_interview_request
    assert request is not None
    selected = next(
        candidate
        for candidate in request.candidates
        if candidate.kind == "authorized_lie"
    )
    result = restored.apply(command, interview_response_id=selected.response_id)

    assert result.accepted and result.dialogue is not None
    assert result.dialogue.text == selected.canonical_claim
    assert result.dialogue.text not in {unsafe_alibi, unsafe_lie}
    assert restored.action_history[-1].interview_rules_version == 2
    assert restore_engine(
        snapshot_engine(restored),
        case,
        location,
    ).runtime == restored.runtime


@pytest.mark.parametrize("kind", ("truthful_observation", "authorized_lie", "evasive"))
def test_engine_records_only_the_selected_authored_interview_claim(kind: str) -> None:
    engine = _generated_engine()
    actor_id = _interviewable_actor_with_all_choice_kinds(engine)
    _begin(engine, actor_id)
    command = InterviewExchangeIntent(message="Tell me what happened.")
    request = engine.preview(command).private_interview_request
    assert request is not None
    selected = next(candidate for candidate in request.candidates if candidate.kind == kind)
    engine.runtime.player_knowledge.known_fact_ids.difference_update(
        selected.referenced_fact_ids
    )
    known_before = set(engine.runtime.player_knowledge.known_fact_ids)

    result = engine.apply(command, interview_response_id=selected.response_id)
    assert result.accepted and result.dialogue is not None
    statement = engine.runtime.player_knowledge.statements[-1]
    assert statement.claim == selected.canonical_claim
    assert statement.referenced_fact_ids == list(selected.referenced_fact_ids)
    discovery_fact_ids = {
        fact_id
        for discovery in result.discoveries
        for fact_id in engine.case.evidence[discovery.id].fact_ids
    }
    claim_granted_fact_ids = (
        engine.runtime.player_knowledge.known_fact_ids - known_before
    ) - discovery_fact_ids
    if kind == "truthful_observation":
        assert set(selected.referenced_fact_ids) <= claim_granted_fact_ids
    else:
        assert not claim_granted_fact_ids


def test_interview_response_id_is_bound_to_the_question_and_exchange() -> None:
    engine = _generated_engine()
    actor_id = _interviewable_actor_with_all_choice_kinds(engine)
    _begin(engine, actor_id)
    first_command = InterviewExchangeIntent(message="What did you see?")
    first_request = engine.preview(first_command).private_interview_request
    assert first_request is not None
    stale = next(
        candidate
        for candidate in first_request.candidates
        if candidate.kind == "truthful_observation"
    )

    changed_command = InterviewExchangeIntent(message="Where were you standing?")
    current_request = engine.preview(changed_command).private_interview_request
    assert current_request is not None
    assert stale.response_id not in {
        candidate.response_id for candidate in current_request.candidates
    }

    result = engine.apply(
        changed_command,
        interview_response_id=stale.response_id,
    )
    fallback = next(
        candidate for candidate in current_request.candidates if candidate.kind == "evasive"
    )
    assert result.accepted and result.dialogue is not None
    assert result.dialogue.text == fallback.canonical_claim


def test_unknown_interview_response_id_uses_the_engine_evasive_fallback() -> None:
    engine = _generated_engine()
    actor_id = _interviewable_actor_with_all_choice_kinds(engine)
    _begin(engine, actor_id)
    command = InterviewExchangeIntent(message="Answer me.")
    request = engine.preview(command).private_interview_request
    assert request is not None
    fallback = next(candidate for candidate in request.candidates if candidate.kind == "evasive")

    result = engine.apply(command, interview_response_id="forged-response-id")
    assert result.accepted and result.dialogue is not None
    statement = engine.runtime.player_knowledge.statements[-1]
    assert statement.claim == fallback.canonical_claim
    assert statement.referenced_fact_ids == []


def test_selected_interview_response_replays_from_a_v2_save() -> None:
    engine = _generated_engine()
    engine.apply(AdvanceOpeningIntent())
    actor_id = next(
        character_id
        for character_id, state in engine.runtime.characters.items()
        if state.alive
        and state.current_room_id == engine.runtime.player_room_id
        and any(
            set(observation.fact_ids).isdisjoint(
                engine.case.overlays[character_id].hides_fact_ids
            )
            for observation in engine.case.overlays[character_id].observations
        )
    )
    assert engine.apply(BeginInterviewIntent(character_id=actor_id)).accepted
    command = InterviewExchangeIntent(message="What did you see?")
    request = engine.preview(command).private_interview_request
    assert request is not None
    selected = next(candidate for candidate in request.candidates if candidate.kind == "truthful_observation")
    engine.apply(command, interview_response_id=selected.response_id)

    restored = restore_engine(snapshot_engine(engine), engine.case, engine.location)
    assert restored.runtime == engine.runtime
    assert restored.action_history == engine.action_history


class _ScenarioInterviewAndPortrayalProvider:
    def __init__(self) -> None:
        self.interview_requests: list[dict[str, object]] = []
        self.portrayal_calls = 0
        self.unexpected_system_prompts: list[str] = []

    async def generate(self, messages, **kwargs):
        system = messages[0].content
        if "canonical scenario architect" in system:
            return SimpleNamespace(
                content=json.dumps(make_dummy_generated_document())
            )
        if "interviewed NPC" in system:
            request = json.loads(messages[-1].content)
            self.interview_requests.append(request)
            selected = next(
                candidate
                for candidate in request["candidates"]
                if candidate["kind"] == "truthful_observation"
            )
            return SimpleNamespace(
                content=json.dumps({"response_id": selected["response_id"]})
            )
        if "Render dialogue only" in system:
            self.portrayal_calls += 1
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "utterance": "I will tell you exactly what I observed.",
                        "referenced_fact_ids": [],
                    }
                )
            )
        self.unexpected_system_prompts.append(system)
        raise AssertionError("unexpected provider call")


class _MalformedInterviewSelectionProvider(_ScenarioInterviewAndPortrayalProvider):
    async def generate(self, messages, **kwargs):
        system = messages[0].content
        if "interviewed NPC" in system:
            request = json.loads(messages[-1].content)
            self.interview_requests.append(request)
            return SimpleNamespace(content="not JSON")
        return await super().generate(messages, **kwargs)


class _BlockingPortrayalProvider(_ScenarioInterviewAndPortrayalProvider):
    def __init__(self) -> None:
        super().__init__()
        self.portrayal_started = asyncio.Event()

    async def generate(self, messages, **kwargs):
        system = messages[0].content
        if "Render dialogue only" in system:
            self.portrayal_calls += 1
            self.portrayal_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        return await super().generate(messages, **kwargs)


async def _start_generated_interview_service(tmp_path, provider) -> tuple[GameService, str]:
    source = load_case("ashwick_sample")
    service = GameService(tmp_path, llm=provider)
    await service.start_generated_async(
        seed=84,
        character_ids=source.character_ids,
    )
    await service.action(AdvanceOpeningIntent())
    engine = service.engine
    assert engine is not None
    actor_id = next(
        character_id
        for character_id, state in engine.runtime.characters.items()
        if state.alive
        and state.current_room_id == engine.runtime.player_room_id
        and any(
            set(observation.fact_ids).isdisjoint(
                engine.case.overlays[character_id].hides_fact_ids
            )
            for observation in engine.case.overlays[character_id].observations
        )
    )
    assert (await service.action(BeginInterviewIntent(character_id=actor_id)))[
        "accepted"
    ]
    return service, actor_id


def test_generated_interview_makes_one_isolated_selection_then_portrayal(
    tmp_path,
) -> None:
    async def scenario() -> None:
        source = load_case("ashwick_sample")
        provider = _ScenarioInterviewAndPortrayalProvider()
        service = GameService(tmp_path, llm=provider)
        await service.start_generated_async(
            seed=84,
            character_ids=source.character_ids,
        )
        await service.action(AdvanceOpeningIntent())
        engine = service.engine
        assert engine is not None
        actor_id = next(
            character_id
            for character_id, state in engine.runtime.characters.items()
            if state.alive
            and state.current_room_id == engine.runtime.player_room_id
            and any(
                set(observation.fact_ids).isdisjoint(
                    engine.case.overlays[character_id].hides_fact_ids
                )
                for observation in engine.case.overlays[
                    character_id
                ].observations
            )
        )
        assert (
            await service.action(BeginInterviewIntent(character_id=actor_id))
        )["accepted"]

        response = await service.action(
            InterviewExchangeIntent(message="What did you observe?")
        )

        assert response["accepted"]
        assert response["dialogue"]["text"] == response["portrayal"][
            "canonical_claim"
        ]
        assert response["portrayal"]["surface_utterance"] == (
            "I will tell you exactly what I observed."
        )
        assert len(provider.interview_requests) == 1
        assert provider.portrayal_calls == 1
        assert not provider.unexpected_system_prompts
        request = provider.interview_requests[0]
        assert request["actor_id"] == actor_id
        serialized = json.dumps(request)
        for other_id, overlay in engine.case.overlays.items():
            if other_id == actor_id:
                continue
            assert overlay.private_motive not in serialized
            for secret in overlay.secrets:
                assert secret not in serialized

    asyncio.run(scenario())


def test_malformed_selector_output_uses_a_useful_engine_fallback(tmp_path) -> None:
    async def scenario() -> None:
        provider = _MalformedInterviewSelectionProvider()
        service, _actor_id = await _start_generated_interview_service(
            tmp_path,
            provider,
        )

        response = await service.action(
            InterviewExchangeIntent(message="Where were you?")
        )

        assert response["accepted"]
        assert len(provider.interview_requests) == 1
        request = provider.interview_requests[0]
        fallback_id = request["fallback_response_id"]
        fallback = next(
            candidate
            for candidate in request["candidates"]
            if candidate["response_id"] == fallback_id
        )
        assert fallback["kind"] == "alibi"
        assert response["dialogue"]["text"] == fallback["canonical_claim"]
        assert response["dialogue"]["text"] != (
            "I am not prepared to say more about that yet."
        )

    asyncio.run(scenario())


def test_cancelling_post_commit_portrayal_returns_one_committed_exchange(
    tmp_path,
) -> None:
    async def scenario() -> None:
        provider = _BlockingPortrayalProvider()
        service, _actor_id = await _start_generated_interview_service(
            tmp_path,
            provider,
        )
        engine = service.engine
        assert engine is not None

        task = asyncio.create_task(
            service.action(InterviewExchangeIntent(message="What did you observe?"))
        )
        await provider.portrayal_started.wait()
        task.cancel()
        response = await task

        assert response["accepted"]
        assert response["portrayal"]["source"] == "fallback"
        assert response["portrayal"]["surface_utterance"] == response["dialogue"][
            "text"
        ]
        assert len(engine.runtime.player_knowledge.statements) == 1
        assert engine.runtime.active_interview is not None
        assert engine.runtime.active_interview.exchanges_used == 1
        assert provider.portrayal_calls == 1

    asyncio.run(scenario())
