"""Adversarial admission tests for generated truth and knowledge boundaries."""

from __future__ import annotations

import pytest

from game.case_generation import GeneratedScenarioError, compile_generated_scenario
from game.content import load_location
from procedural_acceptance_fixture import (
    ARBITRARY_CAST,
    MURDERER_ID,
    independent_generated_document,
)


def _compile(document: dict[str, object]):
    return compile_generated_scenario(
        document,
        character_ids=ARBITRARY_CAST,
        location=load_location("ashwick_manor"),
        seed=731,
    )


def test_provider_cannot_write_player_facing_opening_spoilers() -> None:
    document = independent_generated_document()
    document["case"]["opening"]["discoverer_observations"] = [
        "Gabriel Cross killed the captain with the fireplace poker."
    ]

    with pytest.raises(GeneratedScenarioError, match="invalid generated case schema"):
        _compile(document)


def test_compiler_authors_safe_opening_prose_from_structural_fields() -> None:
    generated = _compile(independent_generated_document())
    opening = generated.case.opening

    assert opening.discoverer_observations == (
        "I found the victim unresponsive and immediately raised the alarm.",
    )
    assert MURDERER_ID not in " ".join(opening.discoverer_observations)
    assert set(opening.initial_reactions) == (
        set(ARBITRARY_CAST)
        - {opening.discoverer_id, generated.case.murder.victim_id}
    )


def test_generated_timeline_rejects_actor_who_is_scheduled_elsewhere() -> None:
    document = independent_generated_document()
    document["case"]["timeline"][0]["actor_ids"].append("celia_marlowe")

    with pytest.raises(
        GeneratedScenarioError,
        match="inconsistent_generated_timeline_location",
    ):
        _compile(document)


def test_generated_hidden_fact_requires_own_observation_provenance() -> None:
    document = independent_generated_document()
    document["case"]["overlays"]["celia_marlowe"]["hides_fact_ids"].append(
        "acceptance_means"
    )

    with pytest.raises(
        GeneratedScenarioError,
        match="unproven_generated_private_knowledge",
    ):
        _compile(document)


def test_generated_known_evidence_requires_observation_provenance() -> None:
    document = independent_generated_document()
    document["case"]["overlays"]["celia_marlowe"][
        "supporting_evidence_ids"
    ].append("acceptance_poker")

    with pytest.raises(
        GeneratedScenarioError,
        match="unproven_generated_evidence_knowledge",
    ):
        _compile(document)


def test_evidence_cannot_implicate_and_exonerate_same_character() -> None:
    document = independent_generated_document()
    document["case"]["evidence"]["acceptance_poker"][
        "exonerates_character_ids"
    ].append(MURDERER_ID)

    with pytest.raises(
        GeneratedScenarioError,
        match="contradictory_evidence_character_effect",
    ):
        _compile(document)


def test_proof_route_cannot_include_clue_that_exonerates_culprit() -> None:
    document = independent_generated_document()
    evidence = document["case"]["evidence"]["acceptance_poker"]
    evidence["implicates_character_ids"] = []
    evidence["exonerates_character_ids"] = [MURDERER_ID]

    with pytest.raises(
        GeneratedScenarioError,
        match="evidence_route_exonerates_culprit",
    ):
        _compile(document)
