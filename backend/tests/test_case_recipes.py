"""Tests for deterministic selection between complete authored crime spines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from game.recipes import (
    MAX_RECIPE_SEED,
    RecipeValidationError,
    case_content_fingerprint,
    resolve_case_recipe,
)


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
