"""Solve representative casts covering every pooled card on both story spines."""

from __future__ import annotations

import pytest

from game.actions import (
    AccuseIntent,
    AdvanceOpeningIntent,
    ExamineBodyIntent,
    MoveIntent,
    SearchIntent,
)
from game.content import load_location
from game.engine import GameEngine
from game.recipes import load_case_recipe, resolve_materialized_case_recipe


RECIPE_ID = "ashwick_manor_dual_spines"
# Greedy set cover over seeds 0..511. Together these eight deterministic draws
# put every one of the 24 cards through each of the two authored mystery spines.
SOAK_SEEDS = (0, 1, 7, 84, 295, 104, 6, 5)


def _discover_solution_path(engine: GameEngine, selected_case_id: str) -> None:
    opening = engine.apply(AdvanceOpeningIntent())
    assert opening.accepted

    if selected_case_id == "ashwick_sample":
        assert engine.apply(MoveIntent(room_id="library")).accepted
        assert engine.apply(ExamineBodyIntent()).accepted
        for object_id in ("library_desk", "library_fireplace"):
            assert engine.apply(SearchIntent(object_id=object_id)).accepted
            assert engine.apply(SearchIntent(object_id=object_id)).accepted
        return

    assert selected_case_id == "ashwick_quiet_vow"
    assert engine.apply(MoveIntent(room_id="chapel")).accepted
    assert engine.apply(ExamineBodyIntent()).accepted
    assert engine.apply(SearchIntent(object_id="chapel_vestry")).accepted
    assert engine.apply(SearchIntent(object_id="chapel_vestry")).accepted
    assert engine.apply(MoveIntent(room_id="great_hall")).accepted
    assert engine.apply(MoveIntent(room_id="gallery")).accepted
    assert engine.apply(SearchIntent(object_id="gallery_portrait")).accepted
    assert engine.apply(SearchIntent(object_id="gallery_portrait")).accepted


def test_soak_seed_matrix_covers_every_card_on_every_story_spine() -> None:
    recipe = load_case_recipe(RECIPE_ID)
    expected = {
        (case_id, card_id)
        for case_id in recipe.case_ids
        for slot in recipe.cast_slots
        for card_id in slot.candidate_card_ids
    }
    actual: set[tuple[str, str]] = set()
    for seed in SOAK_SEEDS:
        selection, _ = resolve_materialized_case_recipe(RECIPE_ID, seed)
        actual.update(
            (selection.selected_case_id, card_id)
            for card_id in selection.slot_card_ids.values()
        )

    assert actual == expected


@pytest.mark.parametrize("seed", SOAK_SEEDS)
def test_each_covering_cast_can_follow_its_full_three_part_solution(seed: int) -> None:
    selection, case = resolve_materialized_case_recipe(RECIPE_ID, seed)
    engine = GameEngine(
        case,
        load_location("ashwick_manor"),
        recipe_selection=selection,
    )
    _discover_solution_path(engine, selection.selected_case_id)

    facts = {fact.id: fact.statement for fact in engine.view().known_facts}
    if selection.selected_case_id == "ashwick_sample":
        motive_fact_id = "fact_financial_exposure"
        timeline_fact_id = "fact_murder_time"
    else:
        motive_fact_id = "fact_certificate_forgery"
        timeline_fact_id = "fact_moreau_gallery_crossing"
    result = engine.apply(
        AccuseIntent(
            character_id=case.murder.murderer_id,
            evidence_ids=sorted(
                engine.runtime.player_knowledge.discovered_evidence_ids
            ),
            method=facts["fact_murder_method"],
            motive=facts[motive_fact_id],
            timeline=facts[timeline_fact_id],
            timeline_fact_ids=[timeline_fact_id],
        )
    )

    assert result.game.result is not None
    assert result.game.result.solved
    assert result.game.result.support_score == 3
    assert set(case.character_ids) == set(selection.slot_card_ids.values())
