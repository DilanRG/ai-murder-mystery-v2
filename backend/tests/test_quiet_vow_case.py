"""Coherence and end-to-end solvability checks for the second Ashwick spine."""

from __future__ import annotations

from game.actions import AccuseIntent, AdvanceOpeningIntent, ExamineBodyIntent, MoveIntent, SearchIntent
from game.content import load_case, load_location
from game.engine import GameEngine
from game.models import CharacterRole
from game.persistence import restore_engine, snapshot_engine
from game.validator import validate_case


CASE_ID = "ashwick_quiet_vow"


def test_quiet_vow_is_a_distinct_valid_ashwick_case() -> None:
    case = load_case(CASE_ID)
    report = validate_case(case, load_location("ashwick_manor"))

    assert report.is_valid, report.issues
    assert case.murder.murderer_id == "dr_celestine_moreau"
    assert case.murder.murderer_id != "edgar_blackwood"
    assert case.murder.weapon_id == "chapel_candlestick"
    assert case.murder.room_id == "chapel"
    assert case.murder.method == "blunt_force"
    assert case.overlays["dr_celestine_moreau"].role is CharacterRole.MURDERER
    assert case.solution.culprit_id == "dr_celestine_moreau"

    # The authored solution has a separate physical, documentary, and route
    # chain; the competing Captain clue is deliberately a red herring only.
    solution_ids = {
        *case.solution.method_evidence_ids,
        *case.solution.motive_evidence_ids,
        *case.solution.opportunity_evidence_ids,
    }
    assert {case.evidence[item].redundancy_group for item in solution_ids} == {
        "means",
        "motive",
        "opportunity",
    }
    assert case.evidence["ev_captain_letter"].is_red_herring
    assert "Moreau" not in case.id and "Moreau" not in case.title


def test_quiet_vow_physical_document_and_route_path_solves_case() -> None:
    engine = GameEngine(load_case(CASE_ID), load_location("ashwick_manor"))
    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="chapel"))
    body = engine.apply(ExamineBodyIntent())
    assert {item.id for item in body.discoveries} == {
        "ev_chapel_candlestick",
        "ev_body_assessment",
    }

    # The vestry is a careful search: the concealed certificate is only found
    # on the second pass.  The gallery trace works the same way.
    engine.apply(SearchIntent(object_id="chapel_vestry"))
    certificate = engine.apply(SearchIntent(object_id="chapel_vestry"))
    assert [item.id for item in certificate.discoveries] == ["ev_vestry_certificate"]
    engine.apply(MoveIntent(room_id="great_hall"))
    engine.apply(MoveIntent(room_id="gallery"))
    engine.apply(SearchIntent(object_id="gallery_portrait"))
    trace = engine.apply(SearchIntent(object_id="gallery_portrait"))
    assert [item.id for item in trace.discoveries] == ["ev_gallery_mud"]

    facts = {fact.id: fact.statement for fact in engine.view().known_facts}
    result = engine.apply(
        AccuseIntent(
            character_id="dr_celestine_moreau",
            method=facts["fact_murder_method"],
            motive=facts["fact_certificate_forgery"],
            timeline=facts["fact_moreau_gallery_crossing"],
        )
    )
    assert result.game.result is not None
    assert result.game.result.solved
    assert result.game.result.support_score == 3

    restored = restore_engine(
        snapshot_engine(engine),
        engine.case,
        engine.location,
    )
    assert restored.runtime.result is not None
    assert restored.runtime.result.solved
    assert restored.runtime == engine.runtime
