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
    timeline_claim_ok = _claim_matches(
        case,
        timeline,
        set(solution.timeline_fact_ids) & known,
    )
    return (
        bool(selected & set(solution.method_evidence_ids)) and method_claim_ok,
        bool(selected & set(solution.motive_evidence_ids)) and motive_claim_ok,
        bool(selected & set(solution.opportunity_evidence_ids)) and timeline_claim_ok,
    )


__all__ = ["evaluate_accusation_support"]
