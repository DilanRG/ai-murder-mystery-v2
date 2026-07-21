"""Deterministic assembly of fully authored mystery cases.

Recipes are deliberately *selection metadata*, not procedural content.  Every
case named by a recipe must already be an authored, independently valid
``CaseDefinition`` for the declared location.  This keeps a seeded replay
honest: the seed picks between complete crime spines, never fabricates one.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictInt, ValidationError, field_validator, model_validator

from game.content import CASES_DIR, CONTENT_DIR, LOCATIONS_DIR
from game.models import CaseDefinition, FrozenModel, LocationPackage
from game.validator import validate_case, validate_location_package


ASSEMBLIES_DIR = CONTENT_DIR / "assemblies"
MAX_RECIPE_SEED = (1 << 63) - 1
_CONTENT_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class RecipeValidationError(ValueError):
    """A recipe is malformed or names content that is not safe to assemble."""


class CaseRecipe(FrozenModel):
    """Strict authored metadata for selecting one complete compatible case."""

    schema_version: Literal[1] = 1
    id: str
    location_package_id: str
    case_ids: tuple[str, ...] = Field(min_length=2)
    case_fingerprints: dict[str, str]

    @field_validator("id", "location_package_id", "case_ids")
    @classmethod
    def validate_content_ids(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        values = value if isinstance(value, tuple) else (value,)
        for content_id in values:
            if not _CONTENT_ID.fullmatch(content_id):
                raise ValueError("must be a lowercase authored content ID")
        return value

    @field_validator("case_fingerprints")
    @classmethod
    def validate_fingerprints(cls, value: dict[str, str]) -> dict[str, str]:
        for case_id, fingerprint in value.items():
            if not _CONTENT_ID.fullmatch(case_id):
                raise ValueError("fingerprint keys must be authored content IDs")
            if not _FINGERPRINT.fullmatch(fingerprint):
                raise ValueError("fingerprints must be lowercase SHA-256 hex digests")
        return value

    @model_validator(mode="after")
    def validate_case_set(self) -> "CaseRecipe":
        if len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("case_ids must not contain duplicates")
        if set(self.case_fingerprints) != set(self.case_ids):
            raise ValueError("case_fingerprints must name exactly case_ids")
        return self


class CaseRecipeSelection(FrozenModel):
    """Safe, persistence-ready record of a reproducible recipe decision."""

    recipe_id: str
    schema_version: Literal[1] = 1
    seed: StrictInt = Field(ge=0, le=MAX_RECIPE_SEED)
    selected_case_id: str
    content_fingerprint: str


def case_content_fingerprint(case: CaseDefinition) -> str:
    """Hash canonical validated case JSON, independent of file whitespace/order."""

    payload = json.dumps(
        case.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _document_path(directory: Path, document_id: str) -> Path:
    if not isinstance(document_id, str) or not _CONTENT_ID.fullmatch(document_id):
        raise RecipeValidationError(f"invalid authored content ID: {document_id!r}")
    path = directory / f"{document_id}.json"
    if not path.is_file():
        raise RecipeValidationError(f"authored content does not exist: {document_id!r}")
    return path


def _load_model(path: Path, model_type: type[CaseRecipe | CaseDefinition | LocationPackage]):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return model_type.model_validate(json.load(handle))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise RecipeValidationError(f"malformed authored document: {path.name}") from error


def load_case_recipe(
    recipe_id: str, *, assemblies_dir: Path = ASSEMBLIES_DIR
) -> CaseRecipe:
    """Load one strict recipe and require its filename to agree with its ID."""

    recipe = _load_model(_document_path(assemblies_dir, recipe_id), CaseRecipe)
    assert isinstance(recipe, CaseRecipe)
    if recipe.id != recipe_id:
        raise RecipeValidationError("recipe filename and embedded id do not match")
    return recipe


def _load_location(location_id: str, locations_dir: Path) -> LocationPackage:
    location = _load_model(_document_path(locations_dir, location_id), LocationPackage)
    assert isinstance(location, LocationPackage)
    if location.id != location_id:
        raise RecipeValidationError("location filename and embedded id do not match")
    location_report = validate_location_package(location)
    if not location_report.is_valid:
        raise RecipeValidationError("recipe location package is invalid")
    return location


def _load_and_validate_case(
    case_id: str,
    *,
    recipe: CaseRecipe,
    location: LocationPackage,
    cases_dir: Path,
) -> CaseDefinition:
    case = _load_model(_document_path(cases_dir, case_id), CaseDefinition)
    assert isinstance(case, CaseDefinition)
    if case.id != case_id:
        raise RecipeValidationError("case filename and embedded id do not match")
    if case.location_package_id != recipe.location_package_id or case.location_package_id != location.id:
        raise RecipeValidationError(f"case {case_id!r} is incompatible with recipe location")
    report = validate_case(case, location)
    if not report.is_valid:
        raise RecipeValidationError(f"case {case_id!r} failed authored-content validation")
    actual_fingerprint = case_content_fingerprint(case)
    if actual_fingerprint != recipe.case_fingerprints[case_id]:
        raise RecipeValidationError(f"case {case_id!r} fingerprint does not match recipe")
    return case


def _validate_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise RecipeValidationError("recipe seed must be an integer")
    if not 0 <= seed <= MAX_RECIPE_SEED:
        raise RecipeValidationError(f"recipe seed must be between 0 and {MAX_RECIPE_SEED}")
    return seed


def _selected_index(recipe: CaseRecipe, seed: int) -> int:
    """Use a specified SHA-256 reduction; never Python's randomized ``hash``."""

    material = f"case-recipe-v1:{recipe.id}:{recipe.schema_version}:{seed}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % len(recipe.case_ids)


def resolve_case_recipe(
    recipe_id: str,
    seed: int,
    *,
    assemblies_dir: Path = ASSEMBLIES_DIR,
    cases_dir: Path = CASES_DIR,
    locations_dir: Path = LOCATIONS_DIR,
) -> CaseRecipeSelection:
    """Validate every named case, then select one reproducibly for ``seed``.

    Validation intentionally happens before selection, so a broken or tampered
    non-selected case can never hide inside a recipe.
    """

    validated_seed = _validate_seed(seed)
    recipe = load_case_recipe(recipe_id, assemblies_dir=assemblies_dir)
    location = _load_location(recipe.location_package_id, locations_dir)
    cases = {
        case_id: _load_and_validate_case(
            case_id, recipe=recipe, location=location, cases_dir=cases_dir
        )
        for case_id in recipe.case_ids
    }
    selected_case_id = recipe.case_ids[_selected_index(recipe, validated_seed)]
    return CaseRecipeSelection(
        recipe_id=recipe.id,
        schema_version=recipe.schema_version,
        seed=validated_seed,
        selected_case_id=selected_case_id,
        content_fingerprint=case_content_fingerprint(cases[selected_case_id]),
    )
