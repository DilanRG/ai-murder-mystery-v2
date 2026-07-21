"""Acceptance contract for a provider-shaped, non-authored generated case."""

from __future__ import annotations

import json

from game.case_generation import compile_generated_scenario
from game.content import load_location
from game.validator import validate_case

from procedural_acceptance_fixture import (
    ARBITRARY_CAST,
    MURDERER_ID,
    independent_generated_document,
)


def _compile(seed: int = 731):
    return compile_generated_scenario(
        independent_generated_document(),
        character_ids=ARBITRARY_CAST,
        location=load_location("ashwick_manor"),
        seed=seed,
    )


def _prerequisite_closure(case, evidence_ids: set[str]) -> set[str]:
    pending = list(evidence_ids)
    closure: set[str] = set()
    while pending:
        evidence_id = pending.pop()
        if evidence_id in closure:
            continue
        closure.add(evidence_id)
        pending.extend(case.evidence[evidence_id].prerequisite_evidence_ids)
    return closure


def test_independent_generated_document_compiles_and_validates() -> None:
    raw_document = independent_generated_document()
    raw_json = json.dumps(raw_document, sort_keys=True)

    assert "ashwick_sample" not in raw_json
    assert "ashwick_quiet_vow" not in raw_json

    compiled = _compile()
    report = validate_case(compiled.case, load_location("ashwick_manor"))

    assert report.is_valid, report.issues
    assert compiled.case.character_ids == ARBITRARY_CAST
    assert compiled.case.id.startswith("generated_")
    assert compiled.case.id not in {"ashwick_sample", "ashwick_quiet_vow"}
    assert compiled.case.murder.murderer_id == MURDERER_ID
    assert len(compiled.case.solution.evidence_routes) == 2


def test_two_disjoint_complete_solution_routes_each_implicate_the_culprit() -> None:
    case = _compile().case
    non_red_solution_evidence = {
        *case.solution.method_evidence_ids,
        *case.solution.motive_evidence_ids,
        *case.solution.opportunity_evidence_ids,
    }
    assert len(non_red_solution_evidence) == 6
    assert all(not case.evidence[evidence_id].is_red_herring for evidence_id in non_red_solution_evidence)
    assert {route.id for route in case.solution.evidence_routes} == {
        "lantern_documentary_route",
        "lantern_trace_route",
    }
    evidence_routes: list[set[str]] = []
    for route in case.solution.evidence_routes:
        evidence_ids = {
            *route.method_evidence_ids,
            *route.motive_evidence_ids,
            *route.opportunity_evidence_ids,
        }
        evidence_routes.append(evidence_ids)
        assert set(route.timeline_fact_ids) <= set(case.solution.timeline_fact_ids)
        assert all(
            case.facts[fact_id].category.value == "timeline"
            for fact_id in route.timeline_fact_ids
        )
        assert all(MURDERER_ID in case.evidence[evidence_id].implicates_character_ids for evidence_id in evidence_ids)
        assert {
            character_id
            for evidence_id in evidence_ids
            for character_id in case.evidence[evidence_id].implicates_character_ids
        } == {MURDERER_ID}

    for route in case.solution.method_evidence_ids, case.solution.motive_evidence_ids, case.solution.opportunity_evidence_ids:
        assert route
    assert case.facts["acceptance_means"].category.value == "means"
    assert case.facts["acceptance_motive"].category.value == "motive"
    assert case.facts["acceptance_opportunity_a"].category.value == "opportunity"
    assert case.facts["acceptance_opportunity_b"].category.value == "opportunity"

    first_evidence, second_evidence = evidence_routes
    assert first_evidence.isdisjoint(second_evidence)
    assert _prerequisite_closure(case, first_evidence).isdisjoint(
        _prerequisite_closure(case, second_evidence)
    )
    first_groups = {case.evidence[evidence_id].redundancy_group for evidence_id in first_evidence}
    second_groups = {case.evidence[evidence_id].redundancy_group for evidence_id in second_evidence}
    assert first_groups.isdisjoint(second_groups)


def test_seven_living_npcs_have_distinct_complete_private_overlays() -> None:
    case = _compile().case
    living = {
        character_id: overlay
        for character_id, overlay in case.overlays.items()
        if character_id != case.murder.victim_id
    }
    assert len(living) == 7
    signatures = set()
    for overlay in living.values():
        assert overlay.observations
        assert overlay.secrets
        assert overlay.relationships
        assert overlay.goals
        assert overlay.initial_suspicions
        assert {
            fact_id
            for observation in overlay.observations
            for fact_id in observation.fact_ids
        }
        signatures.add(
            (
                overlay.private_motive,
                overlay.secrets,
                overlay.goals,
                tuple(sorted(overlay.initial_suspicions.items())),
                overlay.initial_emotional_state,
            )
        )
    assert len(signatures) == 7


def test_independent_generated_document_is_deterministic_by_seed() -> None:
    first = _compile(seed=731)
    second = _compile(seed=731)
    different_seed = _compile(seed=732)

    assert first == second
    assert first.case.id != different_seed.case.id
