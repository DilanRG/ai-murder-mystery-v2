"""Tests for deterministic selection between complete authored crime spines."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from game.recipes import (
    MAX_RECIPE_SEED,
    RecipeValidationError,
    case_content_fingerprint,
    character_card_fingerprint,
    load_case_recipe,
    resolve_case_recipe,
    resolve_materialized_case_recipe,
)


def test_recipe_seed_contract_is_exact_in_the_browser_json_transport() -> None:
    assert MAX_RECIPE_SEED == (1 << 53) - 1
from game.validator import validate_case


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture_content(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    source_root = Path(__file__).resolve().parent.parent / "content"
    location = json.loads((source_root / "locations" / "ashwick_manor.json").read_text())
    original_case = json.loads((source_root / "cases" / "ashwick_sample.json").read_text())
    cases: dict[str, object] = {}
    for case_id in ("fixture_spine_one", "fixture_spine_two"):
        case = {**original_case, "id": case_id, "title": case_id.replace("_", " ").title()}
        cases[case_id] = case
        _write_json(tmp_path / "cases" / f"{case_id}.json", case)
    _write_json(tmp_path / "locations" / "ashwick_manor.json", location)
    fingerprints = {
        case_id: case_content_fingerprint(load_case_from_dict(case))
        for case_id, case in cases.items()
    }
    recipe = {
        "schema_version": 1,
        "id": "fixture_recipe",
        "location_package_id": "ashwick_manor",
        "case_ids": ["fixture_spine_one", "fixture_spine_two"],
        "case_fingerprints": fingerprints,
    }
    _write_json(tmp_path / "assemblies" / "fixture_recipe.json", recipe)
    return tmp_path / "assemblies", tmp_path / "cases", tmp_path / "locations", recipe


def load_case_from_dict(payload: dict[str, object]):
    """Use the production immutable schema for fixture fingerprints."""

    from game.models import CaseDefinition

    return CaseDefinition.model_validate(payload)


def _resolve(tmp_path: Path, seed: int):
    assemblies, cases, locations, _ = _fixture_content(tmp_path)
    return resolve_case_recipe(
        "fixture_recipe",
        seed,
        assemblies_dir=assemblies,
        cases_dir=cases,
        locations_dir=locations,
    )


def test_seeded_selection_is_stable_and_frozen(tmp_path: Path) -> None:
    first = _resolve(tmp_path, 42)
    second = _resolve(tmp_path, 42)

    assert first == second
    assert first.recipe_id == "fixture_recipe"
    assert first.schema_version == 1
    assert first.seed == 42
    assert first.selected_case_id in {"fixture_spine_one", "fixture_spine_two"}
    assert len(first.content_fingerprint) == 64
    with pytest.raises(Exception):
        first.selected_case_id = "fixture_spine_one"  # type: ignore[misc]


def test_production_recipe_resolves_only_validated_authored_spines() -> None:
    selections = {
        resolve_case_recipe("ashwick_manor_dual_spines", seed).selected_case_id
        for seed in range(32)
    }
    assert selections == {"ashwick_sample", "ashwick_quiet_vow"}


@pytest.mark.parametrize("seed", [-1, MAX_RECIPE_SEED + 1, True, "42", 1.5])
def test_seed_rejects_negative_huge_and_non_integer_values(tmp_path: Path, seed: object) -> None:
    with pytest.raises(RecipeValidationError):
        _resolve(tmp_path, seed)  # type: ignore[arg-type]


def test_recipe_rejects_duplicate_or_single_case_ids(tmp_path: Path) -> None:
    assemblies, cases, locations, recipe = _fixture_content(tmp_path)
    recipe["case_ids"] = ["fixture_spine_one"]
    recipe["case_fingerprints"] = {"fixture_spine_one": recipe["case_fingerprints"]["fixture_spine_one"]}  # type: ignore[index]
    _write_json(assemblies / "fixture_recipe.json", recipe)
    with pytest.raises(RecipeValidationError):
        resolve_case_recipe("fixture_recipe", 0, assemblies_dir=assemblies, cases_dir=cases, locations_dir=locations)

    recipe["case_ids"] = ["fixture_spine_one", "fixture_spine_one"]
    recipe["case_fingerprints"] = {"fixture_spine_one": recipe["case_fingerprints"]["fixture_spine_one"]}  # type: ignore[index]
    _write_json(assemblies / "fixture_recipe.json", recipe)
    with pytest.raises(RecipeValidationError):
        resolve_case_recipe("fixture_recipe", 0, assemblies_dir=assemblies, cases_dir=cases, locations_dir=locations)


def test_recipe_rejects_unknown_malformed_bad_location_invalid_case_and_fingerprint(tmp_path: Path) -> None:
    assemblies, cases, locations, recipe = _fixture_content(tmp_path)
    recipe["location_package_id"] = "missing_location"
    _write_json(assemblies / "fixture_recipe.json", recipe)
    with pytest.raises(RecipeValidationError):
        resolve_case_recipe("fixture_recipe", 0, assemblies_dir=assemblies, cases_dir=cases, locations_dir=locations)

    assemblies, cases, locations, recipe = _fixture_content(tmp_path / "malformed-id")
    recipe["case_ids"] = ["fixture_spine_one", "../outside"]
    recipe["case_fingerprints"] = {**recipe["case_fingerprints"], "../outside": "0" * 64}  # type: ignore[arg-type]
    _write_json(assemblies / "fixture_recipe.json", recipe)
    with pytest.raises(RecipeValidationError):
        resolve_case_recipe("fixture_recipe", 0, assemblies_dir=assemblies, cases_dir=cases, locations_dir=locations)

    assemblies, cases, locations, recipe = _fixture_content(tmp_path / "unknown")
    recipe["case_ids"] = ["fixture_spine_one", "missing_case"]
    recipe["case_fingerprints"] = {**recipe["case_fingerprints"], "missing_case": "0" * 64}  # type: ignore[arg-type]
    _write_json(assemblies / "fixture_recipe.json", recipe)
    with pytest.raises(RecipeValidationError):
        resolve_case_recipe("fixture_recipe", 0, assemblies_dir=assemblies, cases_dir=cases, locations_dir=locations)

    assemblies, cases, locations, recipe = _fixture_content(tmp_path / "invalid")
    invalid = json.loads((cases / "fixture_spine_two.json").read_text())
    invalid["solution"]["culprit_id"] = "not_the_murderer"
    _write_json(cases / "fixture_spine_two.json", invalid)
    with pytest.raises(RecipeValidationError):
        resolve_case_recipe("fixture_recipe", 0, assemblies_dir=assemblies, cases_dir=cases, locations_dir=locations)

    assemblies, cases, locations, recipe = _fixture_content(tmp_path / "fingerprint")
    recipe["case_fingerprints"]["fixture_spine_one"] = "0" * 64  # type: ignore[index]
    _write_json(assemblies / "fixture_recipe.json", recipe)
    with pytest.raises(RecipeValidationError):
        resolve_case_recipe("fixture_recipe", 0, assemblies_dir=assemblies, cases_dir=cases, locations_dir=locations)


def test_recipe_rejects_malformed_or_extra_json(tmp_path: Path) -> None:
    assemblies, cases, locations, _ = _fixture_content(tmp_path)
    (assemblies / "fixture_recipe.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RecipeValidationError):
        resolve_case_recipe("fixture_recipe", 0, assemblies_dir=assemblies, cases_dir=cases, locations_dir=locations)

    _, _, _, recipe = _fixture_content(tmp_path / "extra")
    extra_assemblies = tmp_path / "extra" / "assemblies"
    recipe["untrusted"] = "nope"
    _write_json(extra_assemblies / "fixture_recipe.json", recipe)
    with pytest.raises(RecipeValidationError):
        resolve_case_recipe(
            "fixture_recipe",
            0,
            assemblies_dir=extra_assemblies,
            cases_dir=tmp_path / "extra" / "cases",
            locations_dir=tmp_path / "extra" / "locations",
        )


# ── Red tests for deterministic 24-card cast assemblies ─────────────────────


def _canonical_json_fingerprint(document: object) -> str:
    """The fixture's immutable, whitespace-independent authored-card digest."""

    from game.models import GameCharacterCard

    return character_card_fingerprint(GameCharacterCard.model_validate(document))


def _cast_fixture_content(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, dict[str, object]]:
    """Build two valid spines plus eight logical slots with three cards each.

    The current production recipe model intentionally cannot parse this v2
    document yet.  These tests specify the boundary required for cast assembly:
    authored crime spines retain logical slot IDs, while runtime cases receive
    selected CCv3 card IDs.
    """

    assemblies, cases, locations, recipe = _fixture_content(tmp_path)
    source_root = Path(__file__).resolve().parent.parent / "content"
    template = json.loads(
        (source_root / "characters" / "lady_vivienne_ashford.json").read_text(
            encoding="utf-8"
        )
    )
    source_case = json.loads((cases / "fixture_spine_one.json").read_text(encoding="utf-8"))
    slot_ids = source_case["character_ids"]
    assert isinstance(slot_ids, list) and len(slot_ids) == 8

    card_fingerprints: dict[str, str] = {}
    cast_slots: list[dict[str, object]] = []
    characters = tmp_path / "characters"
    for slot_index, slot_id in enumerate(slot_ids):
        candidates: list[str] = []
        for candidate_index in range(3):
            card_id = f"slot{slot_index}_candidate{candidate_index}"
            card = json.loads(json.dumps(template))
            card["data"]["name"] = f"Slot {slot_index} Candidate {candidate_index}"
            card["data"]["extensions"]["murder_mystery"][
                "compatible_case_slots"
            ] = [slot_id]
            _write_json(characters / f"{card_id}.json", card)
            candidates.append(card_id)
            card_fingerprints[card_id] = _canonical_json_fingerprint(card)
        cast_slots.append(
            {
                "id": slot_id,
                "candidate_card_ids": candidates,
                "required_traits": ["fixture-compatible"],
            }
        )

    recipe["schema_version"] = 2
    recipe["cast_slots"] = cast_slots
    recipe["card_fingerprints"] = card_fingerprints
    _write_json(assemblies / "fixture_recipe.json", recipe)
    return assemblies, cases, locations, characters, recipe


def _resolve_cast(tmp_path: Path, seed: int):
    assemblies, cases, locations, characters, _ = _cast_fixture_content(tmp_path)
    return resolve_case_recipe(
        "fixture_recipe",
        seed,
        assemblies_dir=assemblies,
        cases_dir=cases,
        locations_dir=locations,
        characters_dir=characters,
    )


def _materialize_cast(tmp_path: Path, selection: object):
    """Call the intentionally explicit materialization API under test."""

    from game import recipes

    assemblies, cases, locations, characters, _ = _cast_fixture_content(tmp_path)
    return recipes.materialize_case_recipe(
        selection,
        assemblies_dir=assemblies,
        cases_dir=cases,
        locations_dir=locations,
        characters_dir=characters,
    )


def test_cast_selection_is_deterministic_unique_and_constrained_to_each_pool(
    tmp_path: Path,
) -> None:
    assemblies, cases, locations, characters, recipe = _cast_fixture_content(tmp_path)
    first = resolve_case_recipe(
        "fixture_recipe",
        42,
        assemblies_dir=assemblies,
        cases_dir=cases,
        locations_dir=locations,
        characters_dir=characters,
    )
    second = resolve_case_recipe(
        "fixture_recipe",
        42,
        assemblies_dir=assemblies,
        cases_dir=cases,
        locations_dir=locations,
        characters_dir=characters,
    )

    pools = {
        slot["id"]: set(slot["candidate_card_ids"])
        for slot in recipe["cast_slots"]  # type: ignore[index]
    }
    assert first == second
    assert set(first.slot_card_ids) == set(pools)
    assert len(first.slot_card_ids) == 8
    assert len(set(first.slot_card_ids.values())) == 8
    assert all(first.slot_card_ids[slot_id] in candidates for slot_id, candidates in pools.items())
    assert set(first.card_fingerprints) == set(first.slot_card_ids.values())
    assert all(len(fingerprint) == 64 for fingerprint in first.card_fingerprints.values())


def test_every_candidate_is_reachable_over_deterministic_seeds(tmp_path: Path) -> None:
    """A pool is not a real variation pool if one card can never be selected."""

    assemblies, cases, locations, characters, recipe = _cast_fixture_content(tmp_path)
    expected = {
        slot["id"]: set(slot["candidate_card_ids"])
        for slot in recipe["cast_slots"]  # type: ignore[index]
    }
    reached = {slot_id: set() for slot_id in expected}
    for seed in range(256):
        selection = resolve_case_recipe(
            "fixture_recipe",
            seed,
            assemblies_dir=assemblies,
            cases_dir=cases,
            locations_dir=locations,
            characters_dir=characters,
        )
        for slot_id, card_id in selection.slot_card_ids.items():
            reached[slot_id].add(card_id)
    assert reached == expected


def test_production_recipe_declares_a_24_card_pool_and_6561_cast_variations() -> None:
    """Eight disjoint three-card pools have exactly 3**8 cast combinations."""

    recipe = load_case_recipe("ashwick_manor_dual_spines")
    assert len(recipe.cast_slots) == 8
    candidates = [
        card_id for slot in recipe.cast_slots for card_id in slot.candidate_card_ids
    ]
    assert len(candidates) == 24
    assert len(set(candidates)) == 24
    assert all(len(slot.candidate_card_ids) == 3 for slot in recipe.cast_slots)
    assert math.prod(len(slot.candidate_card_ids) for slot in recipe.cast_slots) == 3**8
    assert set(recipe.card_fingerprints) == set(candidates)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_within_pool",
        "duplicate_between_pools",
        "missing_candidate",
        "unknown_candidate",
        "bad_card_fingerprint",
    ],
)
def test_cast_recipe_rejects_malformed_or_tampered_pools(
    tmp_path: Path, mutation: str
) -> None:
    assemblies, cases, locations, characters, recipe = _cast_fixture_content(tmp_path)
    malformed = json.loads(json.dumps(recipe))
    slots = malformed["cast_slots"]
    assert isinstance(slots, list)
    if mutation == "duplicate_within_pool":
        slots[0]["candidate_card_ids"][2] = slots[0]["candidate_card_ids"][0]
    elif mutation == "duplicate_between_pools":
        slots[1]["candidate_card_ids"][0] = slots[0]["candidate_card_ids"][0]
    elif mutation == "missing_candidate":
        slots[0]["candidate_card_ids"].pop()
    elif mutation == "unknown_candidate":
        original = slots[0]["candidate_card_ids"][0]
        slots[0]["candidate_card_ids"][0] = "missing_card"
        malformed["card_fingerprints"].pop(original)
        malformed["card_fingerprints"]["missing_card"] = "0" * 64
    else:
        card_id = slots[0]["candidate_card_ids"][0]
        malformed["card_fingerprints"][card_id] = "0" * 64
    _write_json(assemblies / "fixture_recipe.json", malformed)

    with pytest.raises(RecipeValidationError):
        resolve_case_recipe(
            "fixture_recipe",
            0,
            assemblies_dir=assemblies,
            cases_dir=cases,
            locations_dir=locations,
            characters_dir=characters,
        )


def test_materialized_case_has_selected_ids_and_keeps_full_solvability_validation(
    tmp_path: Path,
) -> None:
    assemblies, cases, locations, characters, _ = _cast_fixture_content(tmp_path)
    selection = resolve_case_recipe(
        "fixture_recipe",
        41,
        assemblies_dir=assemblies,
        cases_dir=cases,
        locations_dir=locations,
        characters_dir=characters,
    )
    materialized = _materialize_cast(tmp_path, selection)
    location = json.loads((locations / "ashwick_manor.json").read_text(encoding="utf-8"))

    from game.models import LocationPackage

    report = validate_case(materialized, LocationPackage.model_validate(location))
    assert report.is_valid, report.issues
    assert set(materialized.character_ids) == set(selection.slot_card_ids.values())
    assert materialized.murder.victim_id == selection.slot_card_ids["lady_vivienne_ashford"]
    assert materialized.murder.murderer_id == selection.slot_card_ids["edgar_blackwood"]
    for evidence in materialized.evidence.values():
        for route in evidence.discoverable_via:
            if route.startswith("interview:"):
                assert route.removeprefix("interview:") in materialized.character_ids


def test_materializer_rejects_a_forged_slot_to_card_mapping(tmp_path: Path) -> None:
    selection = _resolve_cast(tmp_path, 17)
    forged_mapping = dict(selection.slot_card_ids)
    forged_mapping["lady_vivienne_ashford"] = "slot1_candidate0"
    forged = selection.model_copy(update={"slot_card_ids": forged_mapping})

    with pytest.raises(RecipeValidationError):
        _materialize_cast(tmp_path, forged)


@pytest.mark.parametrize("selected_case_id", ["ashwick_sample", "ashwick_quiet_vow"])
def test_materialized_production_prose_replaces_title_and_given_name_together(
    selected_case_id: str,
) -> None:
    recipe = load_case_recipe("ashwick_manor_dual_spines")
    manual_cast = [slot.candidate_card_ids[2] for slot in recipe.cast_slots]
    seed = next(
        candidate_seed
        for candidate_seed in range(32)
        if resolve_case_recipe(
            "ashwick_manor_dual_spines", candidate_seed
        ).selected_case_id
        == selected_case_id
    )

    _, materialized = resolve_materialized_case_recipe(
        "ashwick_manor_dual_spines",
        seed,
        selected_character_ids=manual_cast,
    )
    rendered = json.dumps(materialized.model_dump(mode="json"), ensure_ascii=False)

    assert "Countess Beatrice" in rendered
    assert "Lady Beatrice" not in rendered
    assert "Lady Vivienne" not in rendered
