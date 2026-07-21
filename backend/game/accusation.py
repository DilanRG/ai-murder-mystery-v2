"""Shared, deterministic scoring for evidence-backed accusation claims."""

from __future__ import annotations

from collections.abc import Iterable

from game.models import CaseDefinition


def _normalise(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _claim_matches(
    case: CaseDefinition,
    claim: str,
    candidate_fact_ids: Iterable[str],
) -> bool:
    if not claim.strip():
        return False
    expected = {
        _normalise(case.facts[fact_id].statement)
        for fact_id in candidate_fact_ids
        if fact_id in case.facts
    }
    return _normalise(claim) in expected


def evaluate_accusation_support(
    case: CaseDefinition,
    *,
    known_fact_ids: Iterable[str],
    selected_evidence_ids: Iterable[str],
    selected_timeline_fact_ids: Iterable[str] = (),
    method: str,
    motive: str,
    timeline: str,
) -> tuple[bool, bool, bool]:
    """Score claims only against known facts linked to canonical proof.

    This intentionally accepts authored public fact wording rather than hidden
    murder-record prose.  The same function is used during play and untrusted
    save restoration so their invariants cannot drift apart.
    """

    known = set(known_fact_ids)
    selected = set(selected_evidence_ids)
    solution = case.solution

    def linked_fact_ids(evidence_ids: Iterable[str], category: str) -> set[str]:
        evidence = set(evidence_ids)
        return {
            fact_id
            for fact_id in known
            if fact_id in case.facts
            and case.facts[fact_id].category.value == category
            and set(case.facts[fact_id].related_evidence_ids) & evidence
        }

    method_claim_ok = _claim_matches(
        case,
        method,
        linked_fact_ids(solution.method_evidence_ids, "means"),
    )
    motive_claim_ok = _claim_matches(
        case,
        motive,
        linked_fact_ids(solution.motive_evidence_ids, "motive"),
    )
    timeline_candidates = set(solution.timeline_fact_ids) & known
    if solution.evidence_routes:
        # Generated accusations name the exact timeline fact they rely on.
        # That fact must also be supported by the selected evidence (including
        # prerequisites), preventing a complete route from being paired with
        # an unrelated timeline conclusion from another route.
        evidence_closure: set[str] = set()
        pending = list(selected)
        while pending:
            evidence_id = pending.pop()
            if evidence_id in evidence_closure or evidence_id not in case.evidence:
                continue
            evidence_closure.add(evidence_id)
            pending.extend(case.evidence[evidence_id].prerequisite_evidence_ids)
        evidence_fact_ids = {
            fact_id
            for evidence_id in evidence_closure
            for fact_id in case.evidence[evidence_id].fact_ids
        }
        timeline_candidates &= set(selected_timeline_fact_ids)
        timeline_candidates &= evidence_fact_ids
    timeline_claim_ok = _claim_matches(case, timeline, timeline_candidates)
    return (
        bool(selected & set(solution.method_evidence_ids)) and method_claim_ok,
        bool(selected & set(solution.motive_evidence_ids)) and motive_claim_ok,
        bool(selected & set(solution.opportunity_evidence_ids)) and timeline_claim_ok,
    )


def selected_evidence_supports_complete_route(
    case: CaseDefinition,
    selected_evidence_ids: Iterable[str],
) -> bool:
    """Whether the selected evidence completes one canonical proof route."""

    selected = set(selected_evidence_ids)
    if case.solution.evidence_routes:
        return any(
            {
                *route.method_evidence_ids,
                *route.motive_evidence_ids,
                *route.opportunity_evidence_ids,
            }
            <= selected
            for route in case.solution.evidence_routes
        )
    return all(
        selected & set(axis_ids)
        for axis_ids in (
            case.solution.method_evidence_ids,
            case.solution.motive_evidence_ids,
            case.solution.opportunity_evidence_ids,
        )
    )


__all__ = [
    "evaluate_accusation_support",
    "selected_evidence_supports_complete_route",
]
