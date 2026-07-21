"""Red tests for bounded, engine-authored private NPC social actions.

These tests deliberately select only candidate action IDs.  The eventual
private-agent protocol must not accept provider-authored claims, fact IDs, or
state patches.
"""

from __future__ import annotations

import pytest

from game.actions import AdvanceOpeningIntent, SearchIntent
from game.content import load_case, load_location
from game.engine import GameEngine
from game.models import ConversationMemoryEntry
from game.persistence import (
    SaveValidationError,
    load_engine,
    validate_runtime_state,
    write_save,
)


def _engine() -> GameEngine:
    engine = GameEngine(load_case("ashwick_sample"), load_location("ashwick_manor"))
    assert engine.apply(AdvanceOpeningIntent()).accepted
    return engine


def _isolate_pair(engine: GameEngine) -> tuple[str, str, str]:
    """Put Zara and Edgar together, with every other survivor elsewhere."""

    speaker_id, listener_id, third_party_id = (
        "zara_okonkwo",
        "inspector_elena_hayes",
        "edgar_blackwood",
    )
    spare_rooms = iter(("study", "dining_room", "kitchen", "gallery", "chapel"))
    for character_id, state in engine.runtime.characters.items():
        if not state.alive:
            continue
        state.current_room_id = "library" if character_id in {speaker_id, listener_id} else next(spare_rooms)
    engine.runtime.player_room_id = "great_hall"
    return speaker_id, listener_id, third_party_id


def _private_options(engine: GameEngine) -> dict[str, object]:
    request = engine._build_npc_planning_request()
    return {
        item.actor_id: item
        for item in engine._build_private_npc_requests(request)
    }


def _social_candidate(request: object, phrase: str):
    return next(
        candidate
        for candidate in request.actor_options.candidates
        if phrase in candidate.summary
    )


def _hold_everyone_except(engine: GameEngine, actor_id: str, action_id: str) -> dict[str, str]:
    snapshot = {
        character_id: state.current_room_id
        for character_id, state in engine.runtime.characters.items()
    }
    selections = {actor_id: action_id}
    for character_id, options in engine._npc_candidate_sets(snapshot).items():
        if character_id == actor_id:
            continue
        selections[character_id] = next(
            option_id
            for option_id, intent in options
            if intent.destination_room_id is None
            and intent.manipulate_evidence_id is None
            and getattr(intent, "social", None) is None
        )
    return selections


def test_public_batch_never_offers_private_social_actions() -> None:
    engine = _engine()
    _isolate_pair(engine)

    public_request = engine._build_npc_planning_request()

    assert all(
        not candidate.action_id.startswith("social_")
        and "Privately" not in candidate.summary
        for actor in public_request.actor_options
        for candidate in actor.candidates
    )


def test_private_social_choices_require_a_co_located_pair_away_from_player() -> None:
    engine = _engine()
    speaker_id = "zara_okonkwo"

    engine.runtime.player_room_id = "great_hall"
    for character_id, state in engine.runtime.characters.items():
        if state.alive:
            state.current_room_id = "library" if character_id == speaker_id else "study"
    separated = _private_options(engine)[speaker_id]
    assert not any(
        candidate.action_id.startswith("social_")
        for candidate in separated.actor_options.candidates
    )

    _isolate_pair(engine)
    paired = _private_options(engine)[speaker_id]
    social = [
        candidate
        for candidate in paired.actor_options.candidates
        if candidate.action_id.startswith("social_")
    ]
    assert social
    assert len(social) <= 3
    assert all("Privately" in candidate.summary for candidate in social)

    engine.runtime.player_room_id = "library"
    observed = _private_options(engine)[speaker_id]
    assert not any(
        candidate.action_id.startswith("social_")
        for candidate in observed.actor_options.candidates
    )

    assert all(
        len(request.actor_options.candidates) <= 12
        for request in _private_options(engine).values()
    )


def test_private_observation_claim_transfers_only_to_listener_and_private_memory() -> None:
    engine = _engine()
    speaker_id, listener_id, third_party_id = _isolate_pair(engine)
    before_player_facts = set(engine.runtime.player_knowledge.known_fact_ids)
    before_third_facts = set(engine.runtime.characters[third_party_id].known_fact_ids)

    request = _private_options(engine)[speaker_id]
    observation = _social_candidate(request, "share one known observation")
    engine._run_npc_phase(_hold_everyone_except(engine, speaker_id, observation.action_id))

    expected_fact_ids = {"fact_financial_exposure"}
    assert expected_fact_ids <= engine.runtime.characters[listener_id].known_fact_ids
    assert engine.runtime.player_knowledge.known_fact_ids == before_player_facts
    assert engine.runtime.characters[third_party_id].known_fact_ids == before_third_facts

    speaker_memory = engine.runtime.characters[speaker_id].conversation_memory[-1]
    listener_memory = engine.runtime.characters[listener_id].conversation_memory[-1]
    assert speaker_memory == listener_memory
    assert speaker_memory.speaker_id == speaker_id
    assert speaker_memory.listener_ids == [listener_id]
    assert set(speaker_memory.referenced_fact_ids) == expected_fact_ids
    assert "private" in speaker_memory.topic
    assert all(
        statement.speaker_id != speaker_id
        for statement in engine.runtime.player_knowledge.statements
    )


def test_private_lie_is_recorded_but_never_grants_its_contradicted_facts() -> None:
    engine = _engine()
    speaker_id, listener_id, third_party_id = _isolate_pair(engine)
    contradicted_fact_ids = {"fact_financial_exposure"}
    assert not contradicted_fact_ids <= engine.runtime.characters[listener_id].known_fact_ids
    before_player_facts = set(engine.runtime.player_knowledge.known_fact_ids)
    before_third_facts = set(engine.runtime.characters[third_party_id].known_fact_ids)

    request = _private_options(engine)[speaker_id]
    lie = _social_candidate(request, "authorized claim")
    engine._run_npc_phase(_hold_everyone_except(engine, speaker_id, lie.action_id))

    assert not contradicted_fact_ids <= engine.runtime.characters[listener_id].known_fact_ids
    assert engine.runtime.player_knowledge.known_fact_ids == before_player_facts
    assert engine.runtime.characters[third_party_id].known_fact_ids == before_third_facts
    memory = engine.runtime.characters[speaker_id].conversation_memory[-1]
    assert memory.speaker_id == speaker_id
    assert memory.listener_ids == [listener_id]
    assert memory.referenced_fact_ids == []
    assert "private" in memory.topic


def test_private_claim_is_cancelled_if_its_listener_moves_in_the_same_phase() -> None:
    engine = _engine()
    speaker_id, listener_id, _ = _isolate_pair(engine)
    requests = _private_options(engine)
    observation = _social_candidate(
        requests[speaker_id],
        "share one known observation",
    )
    selections = _hold_everyone_except(
        engine,
        speaker_id,
        observation.action_id,
    )
    selections[listener_id] = next(
        candidate.action_id
        for candidate in requests[listener_id].actor_options.candidates
        if candidate.summary.startswith("Move by an available route")
    )
    before_listener_facts = set(
        engine.runtime.characters[listener_id].known_fact_ids
    )

    engine._run_npc_phase(selections)

    assert engine.runtime.characters[listener_id].current_room_id != "library"
    assert (
        engine.runtime.characters[listener_id].known_fact_ids
        == before_listener_facts
    )
    assert not any(
        memory.speaker_id == speaker_id
        and listener_id in memory.listener_ids
        for memory in engine.runtime.characters[speaker_id].conversation_memory
    )


def test_stale_social_id_cannot_execute_against_a_different_listener() -> None:
    engine = _engine()
    speaker_id, former_listener_id, _ = _isolate_pair(engine)
    stale_observation = _social_candidate(
        _private_options(engine)[speaker_id],
        "share one known observation",
    )
    fact_id = "fact_financial_exposure"
    replacement_id = next(
        character_id
        for character_id, state in engine.runtime.characters.items()
        if state.alive
        and character_id not in {speaker_id, former_listener_id}
        and fact_id not in state.known_fact_ids
    )
    engine.runtime.characters[former_listener_id].current_room_id = "study"
    engine.runtime.characters[replacement_id].current_room_id = "library"
    selections = _hold_everyone_except(
        engine,
        speaker_id,
        stale_observation.action_id,
    )

    engine._run_npc_phase(selections)

    assert fact_id not in engine.runtime.characters[replacement_id].known_fact_ids
    assert not any(
        memory.speaker_id == speaker_id
        and replacement_id in memory.listener_ids
        for memory in engine.runtime.characters[speaker_id].conversation_memory
    )


def test_mutual_social_choices_allow_only_one_interaction_per_participant() -> None:
    engine = _engine()
    first_id, second_id, _ = _isolate_pair(engine)
    requests = _private_options(engine)
    selections = _hold_everyone_except(
        engine,
        first_id,
        _social_candidate(requests[first_id], "authored alibi").action_id,
    )
    selections[second_id] = _social_candidate(
        requests[second_id],
        "authored alibi",
    ).action_id

    engine._run_npc_phase(selections)

    first_memories = [
        memory
        for memory in engine.runtime.characters[first_id].conversation_memory
        if {memory.speaker_id, *memory.listener_ids} == {first_id, second_id}
    ]
    second_memories = [
        memory
        for memory in engine.runtime.characters[second_id].conversation_memory
        if {memory.speaker_id, *memory.listener_ids} == {first_id, second_id}
    ]
    assert len(first_memories) == len(second_memories) == 1
    assert first_memories == second_memories


def test_maximal_actor_facts_are_budgeted_into_a_valid_private_request() -> None:
    engine = _engine()
    murderer_id = engine.case.murder.murderer_id
    expanded_facts = {
        fact_id: fact.model_copy(
            update={"statement": f"{fact_id}:" + "x" * 990}
        )
        for fact_id, fact in engine.case.facts.items()
    }
    engine.case = engine.case.model_copy(update={"facts": expanded_facts})
    engine.runtime.characters[murderer_id].known_fact_ids = set(engine.case.facts)

    request = _private_options(engine)[murderer_id]

    assert len(request.model_dump_json().encode("utf-8")) <= 16_000
    assert request.private_briefing.private_facts[0].id == "host_murder_truth"
    assert request.private_briefing.private_facts


def test_legacy_runtime_rejects_one_sided_private_social_memory() -> None:
    engine = _engine()
    speaker_id, listener_id, _ = _isolate_pair(engine)
    engine.runtime.characters[speaker_id].conversation_memory.append(
        ConversationMemoryEntry(
            turn=engine.runtime.turn,
            speaker_id=speaker_id,
            listener_ids=[listener_id],
            topic="private observation",
            text="A one-sided forged memory.",
            referenced_fact_ids=[],
        )
    )

    with pytest.raises(SaveValidationError, match="private conversation"):
        validate_runtime_state(engine.runtime, engine.case, engine.location)


def test_selected_social_action_replays_exactly_through_a_v2_save(tmp_path) -> None:
    engine = _engine()
    intent = SearchIntent(object_id="hall_clock")
    preview = engine.preview(intent)
    requests = preview.private_npc_requests
    assert requests is not None
    speaker_request = next(
        request
        for request in requests
        if any(
            "share one known observation" in candidate.summary
            for candidate in request.actor_options.candidates
        )
    )
    selections = {
        request.actor_id: next(
            candidate.action_id
            for candidate in request.actor_options.candidates
            if candidate.summary == "Remain in place."
        )
        for request in requests
    }
    selections[speaker_request.actor_id] = _social_candidate(
        speaker_request,
        "share one known observation",
    ).action_id

    result = engine.apply(intent, npc_action_ids=selections)
    assert result.accepted and result.committed
    saved_path = write_save(engine, tmp_path, "social-replay.json")
    restored = load_engine(tmp_path, saved_path.name)

    assert restored.runtime == engine.runtime
    assert restored.action_history == engine.action_history
