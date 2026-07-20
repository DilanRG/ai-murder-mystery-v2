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


def test_initial_npc_knowledge_comes_from_authored_observations_and_secrets() -> None:
    engine = make_engine()
    zara = engine.runtime.characters["zara_okonkwo"]
    assert zara.known_fact_ids == {"fact_financial_exposure", "fact_edgar_left_study"}
    # A relationship to the victim is not itself knowledge of the murderer.
    assert "fact_murderer_identity" not in zara.known_fact_ids


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
            method=known_facts["fact_murder_method"],
            motive=known_facts["fact_financial_exposure"],
            timeline=known_facts["fact_murder_time"],
        )
    )
    assert result.accepted and result.committed
    assert result.game.phase == "ended"
    assert result.game.result is not None and result.game.result.solved
