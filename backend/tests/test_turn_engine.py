"""Behavioural tests for the deterministic, player-safe turn engine."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from game.actions import (
    AccuseIntent,
    AddNoteIntent,
    AddTimelineEntryIntent,
    AdvanceOpeningIntent,
    BeginInterviewIntent,
    EndInterviewIntent,
    ExamineBodyIntent,
    InterviewExchangeIntent,
    MarkContradictionIntent,
    MoveIntent,
    SearchIntent,
    parse_player_intent,
)
from game.content import load_case, load_location
from game.engine import GameEngine
from game.models import CaseDefinition


def make_engine() -> GameEngine:
    return GameEngine(load_case("ashwick_sample"), load_location("ashwick_manor"))


def nested_text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {nested_text(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(nested_text(item) for item in value)
    return str(value)


def test_opening_then_movement_and_search_use_one_turn_each() -> None:
    engine = make_engine()
    assert engine.view().phase == "discovery"
    assert {
        state.current_room_id
        for state in engine.runtime.characters.values()
        if state.alive
    } == {"great_hall"}
    opening = engine.apply(AdvanceOpeningIntent())
    assert opening.accepted and not opening.committed
    assert opening.game.phase == "investigation"
    assert engine.runtime.characters["dr_celestine_moreau"].current_room_id == "library"
    assert engine.runtime.characters["edgar_blackwood"].current_room_id == "study"
    start_minute = engine.runtime.in_game_minute

    moved = engine.apply(MoveIntent(room_id="library"))
    assert moved.accepted and moved.committed
    assert engine.runtime.turn == 1
    assert engine.runtime.in_game_minute == start_minute + 10

    first_search = engine.apply(SearchIntent(object_id="library_desk"))
    assert first_search.accepted and first_search.committed
    assert {item.id for item in first_search.discoveries} == {"ev_sabrina_earring"}
    second_search = engine.apply(SearchIntent(object_id="library_desk"))
    assert {item.id for item in second_search.discoveries} == {
        "ev_edgar_cuff_fibre",
        "ev_vivienne_memo",
    }
    assert engine.runtime.turn == 3
    assert engine.runtime.in_game_minute == start_minute + 30


def test_invalid_move_does_not_change_action_economy() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    before = (engine.runtime.turn, engine.runtime.in_game_minute, engine.runtime.player_room_id)
    result = engine.apply(MoveIntent(room_id="kitchen"))
    assert not result.accepted and not result.committed
    assert (engine.runtime.turn, engine.runtime.in_game_minute, engine.runtime.player_room_id) == before


def test_body_examination_is_a_valid_typed_discovery_route() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))
    assert [scene.id for scene in engine.view().available_scenes] == ["body"]
    result = engine.apply(ExamineBodyIntent())
    assert result.accepted and result.committed
    assert {item.id for item in result.discoveries} == {
        "ev_library_poker",
        "ev_medical_assessment",
        "ev_library_clock",
    }


def test_evidence_prerequisite_must_be_collected_before_discovery() -> None:
    data = load_case("ashwick_sample").model_dump(mode="json")
    data["evidence"]["ev_vivienne_memo"]["prerequisite_evidence_ids"] = [
        "ev_library_poker"
    ]
    engine = GameEngine(
        CaseDefinition.model_validate(data), load_location("ashwick_manor")
    )
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))

    engine.apply(SearchIntent(object_id="library_desk"))
    blocked = engine.apply(SearchIntent(object_id="library_desk"))
    assert "ev_vivienne_memo" not in {item.id for item in blocked.discoveries}
    assert "ev_vivienne_memo" not in engine.runtime.player_knowledge.discovered_evidence_ids

    engine.apply(ExamineBodyIntent())
    admitted = engine.apply(SearchIntent(object_id="library_desk"))
    assert "ev_vivienne_memo" in {item.id for item in admitted.discoveries}


def test_search_cannot_collect_evidence_from_a_different_current_slot() -> None:
    engine = make_engine()
    engine.runtime.evidence["ev_vivienne_memo"].current_slot_id = "slot_study_desk"
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))

    engine.apply(SearchIntent(object_id="library_desk"))
    result = engine.apply(SearchIntent(object_id="library_desk"))

    assert "ev_vivienne_memo" not in {item.id for item in result.discoveries}
    assert "ev_vivienne_memo" not in engine.runtime.player_knowledge.discovered_evidence_ids


def test_interview_cannot_teleport_slotted_evidence_from_another_room() -> None:
    data = load_case("ashwick_sample").model_dump(mode="json")
    data["evidence"]["ev_library_poker"]["discoverable_via"].append(
        "interview:inspector_elena_hayes"
    )
    engine = GameEngine(
        CaseDefinition.model_validate(data), load_location("ashwick_manor")
    )
    engine.apply(AdvanceOpeningIntent())
    engine.apply(BeginInterviewIntent(character_id="inspector_elena_hayes"))

    result = engine.apply(InterviewExchangeIntent(message="What did you find?"))

    assert "ev_library_poker" not in {item.id for item in result.discoveries}
    assert "ev_library_poker" not in engine.runtime.player_knowledge.discovered_evidence_ids


def test_interview_has_three_free_exchanges_and_end_commits_once() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    # Hayes starts in the hall; use the public co-location rule rather than
    # relying on a later NPC movement choice.
    assert engine.apply(BeginInterviewIntent(character_id="inspector_elena_hayes")).accepted
    start = (engine.runtime.turn, engine.runtime.in_game_minute)
    for _ in range(3):
        result = engine.apply(InterviewExchangeIntent(message="What did you see?"))
        assert result.accepted and not result.committed
    assert not engine.apply(InterviewExchangeIntent(message="One more question")).accepted
    assert (engine.runtime.turn, engine.runtime.in_game_minute) == start
    ended = engine.apply(EndInterviewIntent())
    assert ended.accepted and ended.committed
    assert engine.runtime.turn == start[0] + 1
    assert engine.runtime.in_game_minute == start[1] + 10


def test_interview_records_authored_fact_references_and_npc_memory() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(BeginInterviewIntent(character_id="inspector_elena_hayes"))
    alibi = engine.apply(InterviewExchangeIntent(message="Where were you?"))
    observation = engine.apply(InterviewExchangeIntent(message="What did you see?"))

    assert alibi.dialogue is not None and observation.dialogue is not None
    recorded = {statement.id: statement for statement in engine.runtime.player_knowledge.statements}
    assert recorded[alibi.dialogue.id].referenced_fact_ids == []
    assert recorded[observation.dialogue.id].referenced_fact_ids == list(
        engine.case.overlays["inspector_elena_hayes"].observations[0].fact_ids
    )
    memory = engine.runtime.characters["inspector_elena_hayes"].conversation_memory
    assert [entry.text for entry in memory] == [
        recorded[alibi.dialogue.id].claim,
        recorded[observation.dialogue.id].claim,
    ]
    assert memory[-1].listener_ids == ["player"]
    assert memory[-1].referenced_fact_ids == recorded[observation.dialogue.id].referenced_fact_ids


def test_direct_intent_parsing_rejects_blank_interview_before_engine_mutates() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(BeginInterviewIntent(character_id="inspector_elena_hayes"))
    before = (
        engine.runtime.turn,
        engine.runtime.in_game_minute,
        engine.runtime.active_interview.exchanges_used,
        list(engine.runtime.player_knowledge.statements),
    )

    with pytest.raises(ValidationError):
        parse_player_intent({"kind": "interview_exchange", "message": "   "})

    assert (
        engine.runtime.turn,
        engine.runtime.in_game_minute,
        engine.runtime.active_interview.exchanges_used,
        engine.runtime.player_knowledge.statements,
    ) == before


def test_notebook_intents_are_free_and_validate_public_references() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(BeginInterviewIntent(character_id="inspector_elena_hayes"))
    first = engine.apply(InterviewExchangeIntent(message="Where were you?"))
    second = engine.apply(InterviewExchangeIntent(message="What did you see?"))
    assert first.dialogue is not None and second.dialogue is not None
    before = (engine.runtime.turn, engine.runtime.in_game_minute)

    assert engine.apply(AddNoteIntent(text="Compare both accounts.")).accepted
    timeline = engine.apply(
        AddTimelineEntryIntent(
            text="Hayes account",
            minute=1302,
            source_ids=[first.dialogue.id],
        )
    )
    assert timeline.accepted and not timeline.committed
    learned_fact_id = next(fact.id for fact in timeline.game.known_facts)
    fact_timeline = engine.apply(
        AddTimelineEntryIntent(
            text="A learned fact belongs on the working chronology.",
            source_ids=[learned_fact_id],
        )
    )
    assert fact_timeline.accepted and not fact_timeline.committed
    contradiction = engine.apply(
        MarkContradictionIntent(
            left_statement_id=first.dialogue.id,
            right_statement_id=second.dialogue.id,
            note="Check the times.",
        )
    )
    assert contradiction.accepted and not contradiction.committed
    assert not engine.apply(AddTimelineEntryIntent(text="Unsupported", source_ids=["fact_murderer_identity"])).accepted
    assert not engine.apply(
        AddTimelineEntryIntent(
            text="A prediction is not a witnessed event.",
            minute=engine.runtime.in_game_minute + 1,
        )
    ).accepted
    assert not engine.apply(MarkContradictionIntent(left_statement_id=first.dialogue.id, right_statement_id="missing")).accepted
    assert (engine.runtime.turn, engine.runtime.in_game_minute) == before
    notebook = engine.view()
    assert notebook.notes == ["Compare both accounts."]
    assert notebook.statements[0].id == first.dialogue.id
    assert notebook.statements[0].turn == 0
    assert notebook.timeline[0].source_ids == [first.dialogue.id]
    assert notebook.timeline[1].source_ids == [learned_fact_id]
    assert notebook.contradictions[0].left_statement_id == first.dialogue.id


def test_free_notebook_collections_have_a_hard_nonmutating_limit() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    before_clock = (engine.runtime.turn, engine.runtime.in_game_minute)

    for index in range(128):
        result = engine.apply(AddNoteIntent(text=f"note {index}"))
        assert result.accepted and not result.committed
    before_history = len(engine.action_history or [])
    overflow = engine.apply(AddNoteIntent(text="one note too many"))
    assert not overflow.accepted
    assert len(engine.runtime.player_knowledge.notes) == 128
    assert len(engine.action_history or []) == before_history

    for index in range(128):
        result = engine.apply(
            AddTimelineEntryIntent(text=f"timeline item {index}")
        )
        assert result.accepted and not result.committed
    before_history = len(engine.action_history or [])
    overflow = engine.apply(AddTimelineEntryIntent(text="one entry too many"))
    assert not overflow.accepted
    assert len(engine.runtime.player_knowledge.timeline) == 128
    assert len(engine.action_history or []) == before_history
    assert (engine.runtime.turn, engine.runtime.in_game_minute) == before_clock


def test_search_reports_and_persists_discovered_inventory_item() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    result = engine.apply(SearchIntent(object_id="hall_coat_stand"))
    assert [item.id for item in result.items] == ["estate_key"]
    assert "Estate cabinet key" in result.narration
    assert [item.id for item in result.game.inventory] == ["estate_key"]


def test_player_view_never_serializes_hidden_truth_or_unseen_locations() -> None:
    engine = make_engine()
    payload = engine.view().model_dump(mode="json")
    assert payload["known_facts"] == []
    rendered = nested_text(payload)
    for forbidden in (
        "role",
        "murderer_id",
        "fact_murderer_identity",
        "Edgar Blackwood murdered",
        "red_herring",
        "redundancy_group",
        "solution",
        "current_room_id",
        "belief",
        "secret",
    ):
        assert forbidden not in rendered
    assert "Lady Vivienne Ashford" in rendered  # the victim is public in the opening


def test_player_sees_only_the_demeanour_of_characters_in_the_same_room() -> None:
    engine = make_engine()
    character_id = "edgar_blackwood"
    engine.runtime.characters[character_id].emotional_state = "wary"

    view = engine.view()
    present = next(item for item in view.present_characters if item.id == character_id)
    suspect = next(item for item in view.suspects if item.id == character_id)
    assert present.emotional_state == "wary"
    assert suspect.emotional_state == ""

    engine.runtime.characters[character_id].current_room_id = "library"
    hidden_view = engine.view()
    assert character_id not in {item.id for item in hidden_view.present_characters}
    hidden_suspect = next(
        item for item in hidden_view.suspects if item.id == character_id
    )
    assert hidden_suspect.emotional_state == ""


def test_initial_npc_knowledge_comes_from_authored_observations_and_secrets() -> None:
    engine = make_engine()
    zara = engine.runtime.characters["zara_okonkwo"]
    assert zara.known_fact_ids == {"fact_financial_exposure", "fact_edgar_left_study"}
    # A relationship to the victim is not itself knowledge of the murderer.
    assert "fact_murderer_identity" not in zara.known_fact_ids


def test_authored_initial_suspicions_hydrate_bounded_private_beliefs() -> None:
    engine = make_engine()
    victim_id = engine.case.murder.victim_id

    for character_id, character in engine.runtime.characters.items():
        overlay = engine.case.overlays[character_id]
        if character_id == victim_id:
            assert character.beliefs == {}
            continue
        assert {
            subject_id: belief.suspicion
            for subject_id, belief in character.beliefs.items()
        } == overlay.initial_suspicions
        for subject_id, belief in character.beliefs.items():
            assert belief.subject_character_id == subject_id
            assert belief.reason_fact_ids == []
            assert 0 <= belief.suspicion <= 100
            assert "murder" not in belief.summary.casefold()


def _hold_npc_selections(engine: GameEngine) -> dict[str, str]:
    snapshot = {
        character_id: state.current_room_id
        for character_id, state in engine.runtime.characters.items()
    }
    return {
        character_id: next(
            option_id
            for option_id, intent in options
            if intent.destination_room_id is None
            and intent.manipulate_evidence_id is None
        )
        for character_id, options in engine._npc_candidate_sets(snapshot).items()
    }


def _isolate_private_pair(engine: GameEngine, room_id: str) -> tuple[str, str]:
    pair = ("edgar_blackwood", "zara_okonkwo")
    spare_rooms = iter(("study", "dining_room", "kitchen", "gallery", "chapel"))
    for character_id, state in engine.runtime.characters.items():
        if not state.alive:
            continue
        state.current_room_id = room_id if character_id in pair else next(spare_rooms)
    return pair


def test_private_npc_exchange_is_deterministic_bounded_and_not_player_visible() -> None:
    first = make_engine()
    second = make_engine()
    signatures = []
    for engine in (first, second):
        edgar_id, zara_id = _isolate_private_pair(engine, "library")
        engine.runtime.player_room_id = "great_hall"
        engine._run_npc_phase(_hold_npc_selections(engine))

        edgar = engine.runtime.characters[edgar_id]
        zara = engine.runtime.characters[zara_id]
        assert edgar.beliefs[zara_id].suspicion == 85
        assert zara.beliefs[edgar_id].suspicion == 75
        assert edgar.emotional_state == zara.emotional_state == "wary"
        assert len(edgar.conversation_memory) == len(zara.conversation_memory) == 1
        assert edgar.conversation_memory[0] == zara.conversation_memory[0]
        memory = edgar.conversation_memory[0]
        assert memory.speaker_id == edgar_id
        assert memory.listener_ids == [zara_id]
        assert memory.topic == "private exchange"
        assert memory.referenced_fact_ids == []
        assert "murder" not in memory.text.casefold()
        assert sum(
            len(state.conversation_memory)
            for state in engine.runtime.characters.values()
        ) == 2

        public_text = nested_text(engine.view().model_dump(mode="json")).casefold()
        assert "private exchange" not in public_text
        assert "belief" not in public_text
        signatures.append(
            (
                edgar.beliefs[zara_id].model_dump(mode="json"),
                zara.beliefs[edgar_id].model_dump(mode="json"),
                memory.model_dump(mode="json"),
            )
        )
    assert signatures[0] == signatures[1]


def test_player_presence_blocks_private_exchange_and_suspicion_stays_bounded() -> None:
    engine = make_engine()
    edgar_id, zara_id = _isolate_private_pair(engine, "great_hall")
    engine.runtime.player_room_id = "great_hall"
    before = (
        engine.runtime.characters[edgar_id].model_copy(deep=True),
        engine.runtime.characters[zara_id].model_copy(deep=True),
    )
    engine._run_npc_phase(_hold_npc_selections(engine))
    assert engine.runtime.characters[edgar_id] == before[0]
    assert engine.runtime.characters[zara_id] == before[1]

    engine.runtime.player_room_id = "chapel"
    _isolate_private_pair(engine, "library")
    for _ in range(120):
        engine._run_npc_phase(_hold_npc_selections(engine))
    for character_id, subject_id in ((edgar_id, zara_id), (zara_id, edgar_id)):
        character = engine.runtime.characters[character_id]
        assert character.beliefs[subject_id].suspicion == 100
        assert len(character.conversation_memory) == 120
        assert all(memory.referenced_fact_ids == [] for memory in character.conversation_memory)


def test_murderer_cannot_move_and_manipulate_or_act_under_player_observation() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    murderer_id = engine.case.murder.murderer_id
    murderer = engine.runtime.characters[murderer_id]
    murderer.current_room_id = "study"
    engine.runtime.turn = 3
    snapshot = {
        character_id: state.current_room_id
        for character_id, state in engine.runtime.characters.items()
    }

    unobserved = engine._plan_npc(murderer_id, snapshot)
    assert unobserved.manipulate_evidence_id == "ev_audit_fragments"
    assert unobserved.destination_room_id is None

    engine.runtime.player_room_id = "study"
    observed = engine._plan_npc(murderer_id, snapshot)
    assert observed.manipulate_evidence_id is None


def test_case_truth_remains_deeply_immutable_after_play() -> None:
    case = load_case("ashwick_sample")
    before = deepcopy(case.model_dump(mode="json"))
    engine = GameEngine(case, load_location("ashwick_manor"))
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))
    engine.apply(SearchIntent(object_id="library_desk"))
    assert case.model_dump(mode="json") == before
    try:
        case.evidence["ev_library_poker"].description = "tampered"  # type: ignore[misc]
    except (TypeError, ValueError):
        pass
    else:  # pragma: no cover - failure makes the immutable boundary explicit
        raise AssertionError("canonical evidence must be frozen")


def test_accusation_scores_three_evidence_components_and_ends_case() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))
    engine.apply(ExamineBodyIntent())
    engine.apply(SearchIntent(object_id="library_desk"))
    engine.apply(SearchIntent(object_id="library_desk"))
    engine.apply(SearchIntent(object_id="library_fireplace"))
    engine.apply(SearchIntent(object_id="library_fireplace"))
    known_facts = {fact.id: fact.statement for fact in engine.view().known_facts}
    result = engine.apply(
        AccuseIntent(
            character_id="edgar_blackwood",
            evidence_ids=sorted(
                engine.runtime.player_knowledge.discovered_evidence_ids
            ),
            method=known_facts["fact_murder_method"],
            motive=known_facts["fact_financial_exposure"],
            timeline=known_facts["fact_murder_time"],
        )
    )
    assert result.committed and result.game.phase == "ended"
    assert result.game.result is not None
    assert result.game.result.support_score == 3
    assert result.game.result.method_supported
    assert result.game.result.motive_supported
    assert result.game.result.timeline_supported
    assert result.game.result.solved


def test_accusation_never_infers_evidence_the_player_did_not_select() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))
    engine.apply(ExamineBodyIntent())
    engine.apply(SearchIntent(object_id="library_desk"))
    engine.apply(SearchIntent(object_id="library_desk"))
    known_facts = {fact.id: fact.statement for fact in engine.view().known_facts}

    result = engine.apply(
        AccuseIntent(
            character_id="edgar_blackwood",
            method=known_facts["fact_murder_method"],
            motive=known_facts["fact_financial_exposure"],
            timeline=known_facts["fact_murder_time"],
        )
    )

    assert result.game.result is not None
    assert engine.runtime.result is not None
    assert engine.runtime.result.selected_evidence_ids == []
    assert result.game.result.support_score == 0
    assert not result.game.result.solved


def test_blank_or_wrong_accusation_claims_do_not_count_as_support() -> None:
    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))
    engine.apply(ExamineBodyIntent())
    engine.apply(SearchIntent(object_id="library_desk"))
    engine.apply(SearchIntent(object_id="library_desk"))
    blank = engine.apply(AccuseIntent(character_id="edgar_blackwood"))
    assert blank.game.result is not None
    assert blank.game.result.support_score == 0
    assert not blank.game.result.solved
    assert not blank.game.result.method_supported

    engine = make_engine()
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))
    engine.apply(ExamineBodyIntent())
    engine.apply(SearchIntent(object_id="library_desk"))
    engine.apply(SearchIntent(object_id="library_desk"))
    wrong = engine.apply(
        AccuseIntent(
            character_id="edgar_blackwood",
            evidence_ids=sorted(
                engine.runtime.player_knowledge.discovered_evidence_ids
            ),
            method="poison",
            motive={fact.id: fact.statement for fact in engine.view().known_facts}["fact_financial_exposure"],
            timeline={fact.id: fact.statement for fact in engine.view().known_facts}["fact_murder_time"],
        )
    )
    assert wrong.game.result is not None
    assert wrong.game.result.support_score == 2
    assert not wrong.game.result.method_supported
    assert wrong.game.result.solved


def test_full_playthrough_reaches_a_supported_final_accusation() -> None:
    engine = make_engine()
    assert engine.apply(AdvanceOpeningIntent()).game.phase == "investigation"
    assert engine.apply(MoveIntent(room_id="library")).committed
    assert engine.apply(ExamineBodyIntent()).committed
    # The desk needs a careful second pass; its evidence covers motive and opportunity.
    engine.apply(SearchIntent(object_id="library_desk"))
    engine.apply(SearchIntent(object_id="library_desk"))
    known_facts = {fact.id: fact.statement for fact in engine.view().known_facts}
    result = engine.apply(
        AccuseIntent(
            culprit_id="edgar_blackwood",
            evidence_ids=sorted(
                engine.runtime.player_knowledge.discovered_evidence_ids
            ),
            method=known_facts["fact_murder_method"],
            motive=known_facts["fact_financial_exposure"],
            timeline=known_facts["fact_murder_time"],
        )
    )
    assert result.accepted and result.committed
    assert result.game.phase == "ended"
    assert result.game.result is not None and result.game.result.solved
