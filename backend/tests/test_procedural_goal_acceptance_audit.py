"""Red-first goal acceptance and post-game audit contracts for procedural truth."""

from __future__ import annotations

from copy import deepcopy

from game.actions import (
    AccuseIntent,
    AdvanceOpeningIntent,
    MarkContradictionIntent,
    MoveIntent,
    SearchIntent,
)
from game.case_generation import compile_generated_scenario
from game.content import load_location
from game.engine import GameEngine
from game.service import GameService

from procedural_acceptance_fixture import (
    ARBITRARY_CAST,
    MURDERER_ID,
    independent_generated_document,
)


def _engine() -> GameEngine:
    location = load_location("ashwick_manor")
    document = deepcopy(independent_generated_document())
    document["case"]["overlays"][MURDERER_ID]["lies"] = [  # type: ignore[index]
        {
            "id": "acceptance_return_lie",
            "topic": "library clock",
            "claim": "The library clock was running when I left.",
            "contradicts_fact_ids": ["acceptance_timeline_a"],
            "disclosed_fact_ids": [],
            "reason": "The claim conceals the murderer's documented return route.",
        }
    ]
    generated = compile_generated_scenario(
        document,
        character_ids=ARBITRARY_CAST,
        location=location,
        seed=731,
    )
    engine = GameEngine(
        generated.case,
        location,
        story_presentation=generated.presentation,
    )
    assert engine.apply(AdvanceOpeningIntent()).accepted
    return engine


def _apply_with_npc_choices(
    engine: GameEngine,
    intent,
    *,
    actor_summaries: dict[str, str] | None = None,
):
    """Commit through the same finite-choice boundary used by providers."""

    preview = engine.preview(intent)
    assert preview.result.accepted and preview.result.committed
    assert preview.npc_request is not None
    actor_summaries = actor_summaries or {}
    selections: dict[str, str] = {}
    for actor in preview.npc_request.actor_options:
        expected = actor_summaries.get(actor.actor_id, "Remain in place.")
        matching = [
            candidate.action_id
            for candidate in actor.candidates
            if candidate.summary == expected
        ]
        assert len(matching) == 1, (actor.actor_id, expected)
        selections[actor.actor_id] = matching[0]
    result = engine.apply(
        intent,
        npc_action_ids=selections,
        npc_action_sources={actor_id: "host_selection" for actor_id in selections},
    )
    assert result.accepted and result.committed
    return result


def _prepare_goal_evidence(engine: GameEngine) -> tuple[dict[str, str], str]:
    """Discover both proof routes and confirm one contradiction using legal actions."""

    _apply_with_npc_choices(engine, SearchIntent(object_id="hall_coat_stand"))
    _apply_with_npc_choices(
        engine,
        MoveIntent(room_id="library"),
        actor_summaries={
            MURDERER_ID: "Make one pre-authorized misleading claim to the detective.",
            "inspector_maeve_quinn": (
                "Voluntarily disclose one personally known fact to assist the detective."
            ),
        },
    )
    _apply_with_npc_choices(engine, SearchIntent(object_id="library_fireplace"))
    _apply_with_npc_choices(engine, SearchIntent(object_id="library_clock"))
    _apply_with_npc_choices(engine, MoveIntent(room_id="study"))
    _apply_with_npc_choices(engine, SearchIntent(object_id="study_desk"))
    _apply_with_npc_choices(engine, MoveIntent(room_id="library"))
    _apply_with_npc_choices(engine, MoveIntent(room_id="great_hall"))
    _apply_with_npc_choices(engine, SearchIntent(object_id="hall_clock"))
    _apply_with_npc_choices(engine, MoveIntent(room_id="drawing_room"))
    _apply_with_npc_choices(engine, SearchIntent(object_id="drawing_sofa"))

    solution = engine.case.solution
    knowledge = engine.runtime.player_knowledge
    supporting_evidence = {
        *solution.method_evidence_ids,
        *solution.motive_evidence_ids,
        *solution.opportunity_evidence_ids,
    }
    assert supporting_evidence <= knowledge.discovered_evidence_ids
    murderer_statement = next(
        statement
        for statement in knowledge.statements
        if statement.speaker_id == MURDERER_ID
            and statement.claim == "I have no involvement in the death."
    )
    witness_statement = next(
        statement
        for statement in knowledge.statements
        if statement.speaker_id == "inspector_maeve_quinn"
        and "acceptance_timeline_a" in statement.referenced_fact_ids
    )
    marked = engine.apply(
        MarkContradictionIntent(
            left_statement_id=murderer_statement.id,
            right_statement_id=witness_statement.id,
            note="The alibi conflicts with the witness account.",
        )
    )
    assert marked.accepted and not marked.committed
    contradiction = engine.runtime.player_knowledge.contradictions[-1]
    assert contradiction.confirmed

    facts = {fact.id: fact.statement for fact in engine.case.facts.values()}
    return facts, contradiction.id


def test_legacy_three_axis_accusation_fields_remain_compatible() -> None:
    engine = _engine()
    facts, _ = _prepare_goal_evidence(engine)
    solution = engine.case.solution

    result = engine.apply(
        AccuseIntent(
            character_id=MURDERER_ID,
            evidence_ids=[
                *solution.method_evidence_ids,
                *solution.motive_evidence_ids,
                *solution.opportunity_evidence_ids,
            ],
            method=facts["acceptance_means"],
            motive=facts["acceptance_motive"],
            timeline=facts["acceptance_timeline_a"],
            timeline_fact_ids=["acceptance_timeline_a"],
        )
    )

    assert result.accepted and result.game.result is not None
    assert result.game.result.correct_culprit
    assert result.game.result.method_supported
    assert result.game.result.motive_supported
    assert result.game.result.timeline_supported


def test_goal_acceptance_records_confirmed_contradictions_and_selected_support() -> None:
    engine = _engine()
    facts, contradiction_id = _prepare_goal_evidence(engine)
    solution = engine.case.solution
    selected_support = [
        solution.method_evidence_ids[0],
        solution.motive_evidence_ids[0],
        solution.opportunity_evidence_ids[0],
    ]

    result = engine.apply(
        {
            "kind": "accuse",
            "character_id": MURDERER_ID,
            # Existing three-axis claim fields remain the authoritative text
            # contract, while acceptance additionally receives explicit proof.
            "method": facts["acceptance_means"],
            "motive": facts["acceptance_motive"],
            "timeline": facts["acceptance_timeline_a"],
            "timeline_fact_ids": ["acceptance_timeline_a"],
            "selected_supporting_evidence_ids": selected_support,
            "confirmed_contradiction_ids": [contradiction_id],
        }
    )

    assert result.accepted and result.game.result is not None
    verdict = result.game.result.model_dump(mode="json")
    assert verdict["correct_culprit"] is True
    assert verdict["method_supported"] is True
    assert verdict["motive_supported"] is True
    assert verdict["timeline_supported"] is True
    assert verdict["confirmed_contradiction_ids"] == [contradiction_id]
    assert verdict["selected_supporting_evidence_ids"] == sorted(selected_support)
    assert verdict["evidence_supported"] is True
    assert verdict["contradictions_supported"] is True
    assert verdict["evaluation_score"] == 6
    assert verdict["solved"] is True


def test_generated_accusation_cannot_win_with_cross_route_evidence() -> None:
    engine = _engine()
    facts, _ = _prepare_goal_evidence(engine)
    solution = engine.case.solution

    result = engine.apply(
        AccuseIntent(
            character_id=MURDERER_ID,
            evidence_ids=[
                solution.method_evidence_ids[0],
                solution.motive_evidence_ids[1],
                solution.opportunity_evidence_ids[0],
            ],
            method=facts["acceptance_means"],
            motive=facts["acceptance_motive"],
            timeline=facts["acceptance_timeline_a"],
            timeline_fact_ids=["acceptance_timeline_a"],
        )
    )

    assert result.accepted and result.game.result is not None
    assert result.game.result.support_score == 3
    assert result.game.result.evidence_supported is False
    assert result.game.result.solved is False


def test_generated_accusation_rejects_timeline_from_a_different_route() -> None:
    engine = _engine()
    facts, _ = _prepare_goal_evidence(engine)
    route = next(
        item
        for item in engine.case.solution.evidence_routes
        if item.id == "lantern_documentary_route"
    )

    result = engine.apply(
        AccuseIntent(
            character_id=MURDERER_ID,
            evidence_ids=[
                *route.method_evidence_ids,
                *route.motive_evidence_ids,
                *route.opportunity_evidence_ids,
            ],
            method=facts["acceptance_means"],
            motive=facts["acceptance_motive"],
            timeline=facts["acceptance_timeline_b"],
            timeline_fact_ids=["acceptance_timeline_b"],
        )
    )

    assert result.accepted and result.game.result is not None
    assert result.game.result.evidence_supported is True
    assert result.game.result.timeline_supported is False
    assert result.game.result.support_score == 2
    assert result.game.result.solved is False


def test_post_game_audit_explains_procedural_truth_trace_knowledge_and_replay(tmp_path) -> None:
    engine = _engine()
    facts, contradiction_id = _prepare_goal_evidence(engine)
    solution = engine.case.solution
    selected_support = [
        solution.method_evidence_ids[0],
        solution.motive_evidence_ids[0],
        solution.opportunity_evidence_ids[0],
    ]
    result = engine.apply(
        AccuseIntent(
            character_id=MURDERER_ID,
            evidence_ids=selected_support,
            method=facts["acceptance_means"],
            motive=facts["acceptance_motive"],
            timeline=facts["acceptance_timeline_a"],
            timeline_fact_ids=["acceptance_timeline_a"],
            confirmed_contradiction_ids=[contradiction_id],
        )
    )
    assert result.accepted
    service = GameService(tmp_path)
    service.engine = engine

    audit = service.debrief()["audit"]

    truth = audit["canonical_truth"]
    assert truth["culprit_id"] == MURDERER_ID
    assert truth["method"] == engine.case.murder.method
    assert truth["motive"] == engine.case.murder.motive
    assert {route["id"] for route in truth["evidence_routes"]} == {
        route.id for route in engine.case.solution.evidence_routes
    }

    trace = audit["npc_action_trace"]
    assert trace
    assert all(
        {"turn", "actor_id", "proposal", "source", "outcome"} <= set(entry)
        for entry in trace
    )
    assert {entry["actor_id"] for entry in trace} <= set(ARBITRARY_CAST)

    knowledge = audit["final_knowledge"]
    assert set(knowledge["npcs"]) == set(ARBITRARY_CAST)
    assert "acceptance_timeline_a" in knowledge["player"]["known_fact_ids"]
    assert contradiction_id in knowledge["player"]["confirmed_contradiction_ids"]

    replay = audit["replay_verification"]
    assert replay["verified"] is True
    assert replay["action_count"] == len(engine.action_history)
