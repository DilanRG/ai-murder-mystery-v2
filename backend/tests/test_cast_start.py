"""Public API contract tests for one-time deterministic cast selection.

A cast is selected when a new recipe story is created (automatically from its
seed or explicitly by the player) and must remain frozen for the whole saved
story.  These tests deliberately use the public endpoint for start/load; only
pool metadata is read from authored recipe content to construct valid and
adversarial requests.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import main
from game.recipes import load_case_recipe, resolve_case_recipe


RECIPE_ID = "ashwick_manor_dual_spines"


def _client(tmp_path) -> TestClient:
    main._session.engine = None
    main._session.llm = None
    main._session.save_root = tmp_path
    return TestClient(main.app)


def _pools() -> dict[str, tuple[str, ...]]:
    recipe = load_case_recipe(RECIPE_ID)
    return {
        slot.id: tuple(slot.candidate_card_ids)
        for slot in recipe.cast_slots
    }


def _valid_manual_cast() -> list[str]:
    return [candidates[0] for _, candidates in sorted(_pools().items())]


def _new_recipe(client: TestClient, seed: int, character_ids: list[str] | None = None):
    payload: dict[str, object] = {"recipe_id": RECIPE_ID, "seed": seed}
    if character_ids is not None:
        payload["character_ids"] = character_ids
    return client.post("/api/game/new", json=payload)


def _public_cast_ids(payload: dict[str, object]) -> set[str]:
    game = payload["game"]
    assert isinstance(game, dict)
    suspects = game["suspects"]
    assert isinstance(suspects, list)
    cast_ids = {str(suspect["id"]) for suspect in suspects}
    # The victim is deliberately not a living suspect, but remains part of the
    # selected eight-card cast and is public in the discovery opening.
    opening = game.get("opening")
    if isinstance(opening, dict):
        cast_ids.add(str(opening["victim_id"]))
    return cast_ids


def _assert_no_cast_internal_metadata(payload: object) -> None:
    serialized = json.dumps(payload).lower()
    for forbidden in (
        "slot_card_ids",
        "card_fingerprints",
        "cast_slots",
        "materialized_case_fingerprint",
        "slot_murderer",
        "slot_victim",
    ):
        assert forbidden not in serialized


def test_manual_cast_is_selected_at_new_story_start_and_exposed_only_as_cards(tmp_path) -> None:
    manual_cast = _valid_manual_cast()
    with _client(tmp_path) as client:
        response = _new_recipe(client, seed=91, character_ids=manual_cast)

    assert response.status_code == 200
    payload = response.json()
    assert _public_cast_ids(payload) == set(manual_cast)
    assert payload["recipe"] == {
        "recipe_id": RECIPE_ID,
        "schema_version": 2,
        "seed": 91,
        "cast_mode": "manual",
        "story_source": "fallback",
        "story_status": "ready",
    }
    _assert_no_cast_internal_metadata(payload)


@pytest.mark.parametrize(
    "invalid_kind",
    ["empty", "seven", "nine", "duplicate", "unknown", "two_from_one_pool"],
)
def test_recipe_start_rejects_invalid_manual_casts(tmp_path, invalid_kind: str) -> None:
    manual_cast = _valid_manual_cast()
    pools = _pools()
    if invalid_kind == "empty":
        invalid = []
    elif invalid_kind == "seven":
        invalid = manual_cast[:-1]
    elif invalid_kind == "nine":
        invalid = [*manual_cast, "extra_card"]
    elif invalid_kind == "duplicate":
        invalid = [*manual_cast[:-1], manual_cast[0]]
    elif invalid_kind == "unknown":
        invalid = [*manual_cast[:-1], "not_a_card"]
    else:
        first_slot, second_slot = sorted(pools)[:2]
        replacement = pools[first_slot][1]
        assert replacement != manual_cast[0]
        invalid = list(manual_cast)
        invalid[sorted(pools).index(second_slot)] = replacement

    with _client(tmp_path) as client:
        response = _new_recipe(client, seed=8, character_ids=invalid)

    assert response.status_code in {400, 422}
    assert main._session.engine is None


def test_manual_cast_is_not_accepted_for_a_fixed_case_start(tmp_path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/game/new",
            json={
                "case_id": "ashwick_sample",
                "location_id": "ashwick_manor",
                "character_ids": _valid_manual_cast(),
            },
        )

    assert response.status_code in {400, 422}
    assert main._session.engine is None


def test_same_seed_and_manual_cast_reproduce_exactly(tmp_path) -> None:
    manual_cast = _valid_manual_cast()
    with _client(tmp_path) as client:
        first = _new_recipe(client, seed=1234, character_ids=manual_cast)
        second = _new_recipe(client, seed=1234, character_ids=manual_cast)

    assert first.status_code == second.status_code == 200
    first_payload, second_payload = first.json(), second.json()
    assert _public_cast_ids(first_payload) == _public_cast_ids(second_payload) == set(manual_cast)
    assert first_payload["recipe"] == second_payload["recipe"]
    _assert_no_cast_internal_metadata(first_payload)


def test_automatic_cast_changes_by_seed_and_each_card_is_reachable() -> None:
    pools = _pools()
    first = resolve_case_recipe(RECIPE_ID, 0)
    different = next(
        selection
        for seed in range(1, 256)
        if (selection := resolve_case_recipe(RECIPE_ID, seed)).slot_card_ids
        != first.slot_card_ids
    )
    assert different.seed != first.seed
    assert first.cast_mode == different.cast_mode == "automatic"

    reached = {slot_id: set() for slot_id in pools}
    for seed in range(256):
        selection = resolve_case_recipe(RECIPE_ID, seed)
        for slot_id, card_id in selection.slot_card_ids.items():
            reached[slot_id].add(card_id)
    assert reached == {slot_id: set(candidates) for slot_id, candidates in pools.items()}


def test_automatic_start_exposes_mode_but_not_selection_mapping(tmp_path) -> None:
    with _client(tmp_path) as client:
        response = _new_recipe(client, seed=44)

    assert response.status_code == 200
    payload = response.json()
    assert payload["recipe"] == {
        "recipe_id": RECIPE_ID,
        "schema_version": 2,
        "seed": 44,
        "cast_mode": "automatic",
        "story_source": "fallback",
        "story_status": "ready",
    }
    assert len(_public_cast_ids(payload)) == 8
    _assert_no_cast_internal_metadata(payload)


def test_save_load_preserves_manual_cast_exactly_after_a_different_story_starts(tmp_path) -> None:
    manual_cast = _valid_manual_cast()
    with _client(tmp_path) as client:
        started = _new_recipe(client, seed=700, character_ids=manual_cast)
        assert started.status_code == 200
        saved = client.post("/api/game/saves/v2", json={"filename": "manual-cast.json"})
        assert saved.status_code == 200

        replacement = _new_recipe(client, seed=701)
        assert replacement.status_code == 200
        assert _public_cast_ids(replacement.json()) != set(manual_cast)

        loaded = client.post("/api/game/saves/v2/manual-cast.json/load")

    assert loaded.status_code == 200
    payload = loaded.json()
    assert _public_cast_ids(payload) == set(manual_cast)
    assert payload["recipe"] == {
        "recipe_id": RECIPE_ID,
        "schema_version": 2,
        "seed": 700,
        "cast_mode": "manual",
        "story_source": "fallback",
        "story_status": "ready",
    }
    _assert_no_cast_internal_metadata(payload)
