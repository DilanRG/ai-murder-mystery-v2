"""Red acceptance contracts for generated-case NPC autonomy and auditability.

These tests intentionally exercise a provider-shaped procedural case instead of
either authored spine.  NPCs may select host-authored action IDs, but every
effect and every audit record remains engine-owned and replayable.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
import json
import re

from game.actions import AdvanceOpeningIntent, SearchIntent
from game.case_generation import compile_generated_scenario
from game.content import load_location
from game.engine import GameEngine
from game.models import EvidenceCondition
from game.persistence import load_engine, write_save
from procedural_acceptance_fixture import (
    ARBITRARY_CAST,
    DISCOVERER_ID,
    MURDERER_ID,
    independent_generated_document,
)


def _engine(*, with_authorized_misdirection: bool = False) -> GameEngine:
    document = deepcopy(independent_generated_document())
    if with_authorized_misdirection:
        document["case"]["overlays"][MURDERER_ID]["lies"] = [  # type: ignore[index]
            {
                "id": "acceptance_misdirection",
                "topic": "return route",
                "claim": "I remained in the great hall after the alarm.",
                "contradicts_fact_ids": ["acceptance_timeline_b"],
                "disclosed_fact_ids": [],
                "reason": "The host-authored lie protects the murderer without teaching its target a fact.",
            }
        ]
    generated = compile_generated_scenario(
        document,
        character_ids=ARBITRARY_CAST,
        location=load_location("ashwick_manor"),
        seed=731,
    )
    engine = GameEngine(
        generated.case,
        load_location("ashwick_manor"),
        story_presentation=generated.presentation,
    )
    assert engine.apply(AdvanceOpeningIntent()).accepted
    return engine


def _snapshot(engine: GameEngine) -> dict[str, str]:
    return {
        character_id: state.current_room_id
        for character_id, state in engine.runtime.characters.items()
        if state.alive
    }


def _options(engine: GameEngine, actor_id: str):
    return engine._npc_candidate_sets(  # noqa: SLF001 - acceptance boundary
        _snapshot(engine),
        include_private_social=True,
    )[actor_id]


def _select(engine: GameEngine, actor_id: str, kind: str, **targets: str):
    """Select a typed host-authored action without relying on candidate order."""

    for action_id, intent in _options(engine, actor_id):
        if getattr(intent, "kind", None) != kind:
            continue
        if all(getattr(intent, key, None) == value for key, value in targets.items()):
            return action_id
    raise AssertionError(f"missing {kind} action for {actor_id}: {targets}")


def _wait_elsewhere(engine: GameEngine, actor_id: str, action_id: str) -> dict[str, str]:
    selected = {actor_id: action_id}
    for character_id in _snapshot(engine):
        if character_id != actor_id:
            selected[character_id] = _select(engine, character_id, "wait")
    return selected


def _intent_signature(intent: object) -> str:
    value = asdict(intent) if is_dataclass(intent) else vars(intent)
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def test_procedural_survivors_have_seven_distinct_private_states_and_goal_intentions() -> None:
    engine = _engine()
    survivors = {
        character_id: state
        for character_id, state in engine.runtime.characters.items()
        if state.alive
    }

    assert set(survivors) == set(ARBITRARY_CAST) - {"captain_marcus_drake"}
    assert len(survivors) == 7
    assert len({state.emotional_state for state in survivors.values()}) == 7
    assert len({tuple(sorted(state.known_fact_ids)) for state in survivors.values()}) == 7
    for character_id, state in survivors.items():
        assert state.intentions == list(engine.case.overlays[character_id].goals)
        assert state.intentions, character_id


def test_npc_action_ids_are_semantic_stable_and_never_positional() -> None:
    engine = _engine()
    actor_id = DISCOVERER_ID
    first = {
        _intent_signature(intent): action_id
        for action_id, intent in _options(engine, actor_id)
    }
    assert first
    assert all(not re.fullmatch(r"option_\d+", action_id) for action_id in first.values())

    # Candidate enumeration order is not part of the replay contract.
    engine.runtime.characters = dict(reversed(list(engine.runtime.characters.items())))
    second = {
        _intent_signature(intent): action_id
        for action_id, intent in _options(engine, actor_id)
    }
    assert second == first


def test_host_resolved_investigation_grants_only_the_acting_npc_in_place_knowledge() -> None:
    engine = _engine()
    actor_id = DISCOVERER_ID
    engine.runtime.player_room_id = "great_hall"
    engine.runtime.characters[actor_id].current_room_id = "library"
    before_player_facts = set(engine.runtime.player_knowledge.known_fact_ids)
    before_player_evidence = set(engine.runtime.player_knowledge.discovered_evidence_ids)

    action_id = _select(
        engine,
        actor_id,
        "investigate",
        evidence_id="acceptance_poker",
    )
    engine._run_npc_phase(_wait_elsewhere(engine, actor_id, action_id))  # noqa: SLF001

    actor = engine.runtime.characters[actor_id]
    assert "acceptance_poker" in actor.known_evidence_ids
    assert "acceptance_means" in actor.known_fact_ids
    assert engine.runtime.evidence["acceptance_poker"].discovered_by_character_ids == {actor_id}
    assert engine.runtime.player_knowledge.known_fact_ids == before_player_facts
    assert engine.runtime.player_knowledge.discovered_evidence_ids == before_player_evidence


def test_npc_can_explicitly_approach_the_player_without_a_player_selected_move() -> None:
    engine = _engine()
    actor_id = "celia_marlowe"
    engine.runtime.player_room_id = "library"
    engine.runtime.characters[actor_id].current_room_id = "great_hall"

    action_id = _select(engine, actor_id, "approach_player", target_room_id="library")
    engine._run_npc_phase(_wait_elsewhere(engine, actor_id, action_id))  # noqa: SLF001

    assert engine.runtime.characters[actor_id].current_room_id == "library"
    assert engine.runtime.characters[actor_id].current_activity == "approaching player"


def test_truthful_assistance_discloses_host_known_facts_but_misdirection_never_grants_them() -> None:
    engine = _engine(with_authorized_misdirection=True)
    truthful_id = DISCOVERER_ID
    engine.runtime.player_room_id = "library"
    engine.runtime.characters[truthful_id].current_room_id = "library"
    engine.runtime.characters[truthful_id].known_fact_ids.add("acceptance_timeline_a")

    truthful_action = _select(
        engine,
        truthful_id,
        "truthful_disclose",
        fact_id="acceptance_timeline_a",
    )
    engine._run_npc_phase(_wait_elsewhere(engine, truthful_id, truthful_action))  # noqa: SLF001
    assert "acceptance_timeline_a" in engine.runtime.player_knowledge.known_fact_ids
    statement = engine.runtime.player_knowledge.statements[-1]
    assert statement.referenced_fact_ids == [
        "acceptance_timeline_a"
    ]
    truthful_audit = next(
        entry
        for entry in reversed(engine.runtime.npc_action_audit)
        if entry.actor_id == truthful_id
    )
    deltas = {
        delta.participant_id: delta
        for delta in truthful_audit.participant_knowledge_deltas
    }
    assert deltas[truthful_id].fact_ids_shared == ["acceptance_timeline_a"]
    assert deltas["player"].fact_ids_gained == ["acceptance_timeline_a"]
    assert deltas["player"].statement_ids_heard == [statement.id]

    engine.runtime.characters[MURDERER_ID].current_room_id = "library"
    before_facts = set(engine.runtime.player_knowledge.known_fact_ids)
    misdirect_action = _select(engine, MURDERER_ID, "authorized_misdirect")
    engine._run_npc_phase(_wait_elsewhere(engine, MURDERER_ID, misdirect_action))  # noqa: SLF001
    assert engine.runtime.player_knowledge.known_fact_ids == before_facts
    assert engine.runtime.player_knowledge.statements[-1].referenced_fact_ids == []


def test_generated_murderer_autonomous_claim_never_exposes_provider_prose() -> None:
    engine = _engine(with_authorized_misdirection=True)
    raw_claim = "The death was my work; I arranged every detail myself."
    overlay = engine.case.overlays[MURDERER_ID]
    poisoned_lie = overlay.lies[0].model_copy(
        update={"topic": "my private confession", "claim": raw_claim}
    )
    engine.case = engine.case.model_copy(
        update={
            "overlays": {
                **engine.case.overlays,
                MURDERER_ID: overlay.model_copy(update={"lies": (poisoned_lie,)}),
            }
        }
    )
    engine.runtime.player_room_id = "library"
    engine.runtime.characters[MURDERER_ID].current_room_id = "library"

    action_id = _select(engine, MURDERER_ID, "authorized_misdirect")
    engine._run_npc_phase(  # noqa: SLF001
        _wait_elsewhere(engine, MURDERER_ID, action_id)
    )
    statement = engine.runtime.player_knowledge.statements[-1]
    assert statement.claim != raw_claim
    assert raw_claim not in statement.claim
    assert statement.topic == "account"
    assert statement.claim == "I have no involvement in the death."


def test_private_information_exchange_audits_the_recipient_knowledge_gain() -> None:
    engine = _engine()
    actor_id = DISCOVERER_ID
    target_id = "celia_marlowe"
    engine.runtime.player_room_id = "great_hall"
    for character_id, state in engine.runtime.characters.items():
        if state.alive:
            state.current_room_id = (
                "library"
                if character_id in {actor_id, target_id}
                else "great_hall"
            )
    social_action_id = next(
        action_id
        for action_id, intent in _options(engine, actor_id)
        if intent.social is not None
        and intent.social.target_character_id == target_id
        and intent.social.transfers_facts
        and not set(intent.social.referenced_fact_ids)
        <= engine.runtime.characters[target_id].known_fact_ids
    )
    engine._run_npc_phase(  # noqa: SLF001
        _wait_elsewhere(engine, actor_id, social_action_id)
    )

    audit = next(
        entry
        for entry in reversed(engine.runtime.npc_action_audit)
        if entry.actor_id == actor_id
    )
    deltas = {
        delta.participant_id: delta
        for delta in audit.participant_knowledge_deltas
    }
    assert deltas[actor_id].fact_ids_shared
    assert deltas[target_id].fact_ids_gained == deltas[actor_id].fact_ids_shared


def test_world_event_reaction_is_host_resolved_and_auditable() -> None:
    engine = _engine()
    engine.runtime.turn = 6
    engine._run_location_events()  # noqa: SLF001
    assert engine.runtime.event_log[-1].id == "storm_intensifies"
    actor_id = "chef_armand_dubois"

    action_id = _select(
        engine,
        actor_id,
        "react_world_event",
        event_id="storm_intensifies",
    )
    engine._run_npc_phase(_wait_elsewhere(engine, actor_id, action_id))  # noqa: SLF001
    assert engine.runtime.characters[actor_id].current_activity.startswith("reacted:")


def test_murderer_counterplay_cannot_remove_the_last_complete_generated_route() -> None:
    engine = _engine()
    engine.runtime.turn = 3
    engine.runtime.player_room_id = "library"
    engine.runtime.characters[MURDERER_ID].current_room_id = "great_hall"
    initial_candidates = dict(_options(engine, MURDERER_ID))
    assert any(
        getattr(intent, "kind", None) == "conceal_evidence"
        and getattr(intent, "evidence_id", None) == "acceptance_metal_trace"
        for intent in initial_candidates.values()
    )

    # Destroy the documentary route; the trace route is now the only complete
    # means/motive/opportunity/timeline path left to the culprit.
    for evidence_id in ("acceptance_poker", "acceptance_accounts", "acceptance_clock"):
        engine.runtime.evidence[evidence_id].condition = EvidenceCondition.DESTROYED
        engine.runtime.evidence[evidence_id].current_slot_id = None
    candidates = dict(_options(engine, MURDERER_ID))
    assert not any(
        getattr(intent, "kind", None) == "conceal_evidence"
        and getattr(intent, "evidence_id", None) == "acceptance_metal_trace"
        for intent in candidates.values()
    )
    assert engine.runtime.evidence["acceptance_metal_trace"].condition is EvidenceCondition.IN_PLACE


def test_resolved_npc_audit_is_normalized_and_replays_byte_identically(tmp_path) -> None:
    engine = _engine()
    result = engine.apply(SearchIntent(object_id="hall_clock"))
    assert result.accepted and result.committed

    audit = engine.action_history[-1].model_dump(mode="json")["resolved_npc_actions"]
    assert len(audit) == 7
    assert {entry["actor_id"] for entry in audit} == {
        character_id
        for character_id, state in engine.runtime.characters.items()
        if state.alive
    }
    assert all(
        set(entry) == {
            "actor_id",
            "requested_action_id",
            "resolved_action_id",
            "kind",
            "outcome",
            "reason",
            "knowledge_delta",
            "participant_knowledge_deltas",
        }
        for entry in audit
    )
    assert all(
        set(entry["knowledge_delta"]) == {
            "fact_ids_gained",
            "fact_ids_shared",
            "evidence_ids_gained",
            "statement_ids_heard",
        }
        for entry in audit
    )

    saved = write_save(engine, tmp_path, "procedural-npc-audit.json")
    restored = load_engine(tmp_path, saved.name)
    assert restored.action_history[-1].model_dump(mode="json")["resolved_npc_actions"] == audit
    assert restored.runtime.model_dump(mode="json") == engine.runtime.model_dump(mode="json")
