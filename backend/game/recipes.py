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
from typing import Iterable, Literal

from pydantic import Field, StrictInt, ValidationError, field_validator, model_validator

from game.content import CASES_DIR, CHARACTER_CARDS_DIR, CONTENT_DIR, LOCATIONS_DIR
from game.models import CaseDefinition, FrozenModel, GameCharacterCard, LocationPackage
from game.validator import validate_case, validate_location_package


ASSEMBLIES_DIR = CONTENT_DIR / "assemblies"
# Recipe seeds cross the browser JSON boundary as numbers, so keep every
# accepted value exactly representable in both Python and JavaScript.
MAX_RECIPE_SEED = (1 << 53) - 1
_CONTENT_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class RecipeValidationError(ValueError):
    """A recipe is malformed or names content that is not safe to assemble."""


class CastSlot(FrozenModel):
    """One logical authored role and its three interchangeable CCv3 cards."""

    id: str
    candidate_card_ids: tuple[str, str, str]
    required_traits: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("id", "candidate_card_ids")
    @classmethod
    def validate_content_ids(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        values = value if isinstance(value, tuple) else (value,)
        if any(not _CONTENT_ID.fullmatch(content_id) for content_id in values):
            raise ValueError("cast slots must use lowercase authored content IDs")
        return value


class CaseRecipe(FrozenModel):
    """Strict authored metadata for selecting one complete compatible case."""

    schema_version: Literal[1, 2] = 1
    id: str
    location_package_id: str
    case_ids: tuple[str, ...] = Field(min_length=2)
    case_fingerprints: dict[str, str]
    cast_slots: tuple[CastSlot, ...] = Field(default_factory=tuple)
    card_fingerprints: dict[str, str] = Field(default_factory=dict)

    @field_validator("id", "location_package_id", "case_ids")
    @classmethod
    def validate_content_ids(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        values = value if isinstance(value, tuple) else (value,)
        for content_id in values:
            if not _CONTENT_ID.fullmatch(content_id):
                raise ValueError("must be a lowercase authored content ID")
        return value

    @field_validator("case_fingerprints", "card_fingerprints")
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
        slot_ids = [slot.id for slot in self.cast_slots]
        candidate_ids = [
            character_id
            for slot in self.cast_slots
            for character_id in slot.candidate_card_ids
        ]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("cast slot IDs must be unique")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("character candidates must be globally unique")
        if self.cast_slots and set(self.card_fingerprints) != set(candidate_ids):
            raise ValueError("card_fingerprints must name every pooled card exactly once")
        if not self.cast_slots and self.card_fingerprints:
            raise ValueError("card_fingerprints require cast_slots")
        if self.schema_version == 1 and self.cast_slots:
            raise ValueError("cast slots require recipe schema version 2")
        if self.schema_version == 2 and len(self.cast_slots) != 8:
            raise ValueError("recipe schema version 2 requires exactly eight cast slots")
        return self


class CaseRecipeSelection(FrozenModel):
    """Safe, persistence-ready record of a reproducible recipe decision."""

    recipe_id: str
    schema_version: Literal[1, 2] = 1
    seed: StrictInt = Field(ge=0, le=MAX_RECIPE_SEED)
    selected_case_id: str
    content_fingerprint: str
    cast_mode: Literal["automatic", "manual"] = "automatic"
    slot_card_ids: dict[str, str] = Field(default_factory=dict)
    card_fingerprints: dict[str, str] = Field(default_factory=dict)


def case_content_fingerprint(case: CaseDefinition) -> str:
    """Hash canonical validated case JSON, independent of file whitespace/order."""

    document = case.model_dump(mode="json")
    # Semantic Stage 1 fields were added after the authored foundation was
    # fingerprinted. Keep legacy case/save/recipe compatibility byte-stable.
    if document.get("stage1_contract_version") == "legacy":
        document.pop("stage1_contract_version", None)
        if not document.get("case_means"):
            document.pop("case_means", None)
        murder = document["murder"]
        if murder.get("death_mode") == "homicide":
            murder.pop("death_mode", None)
        if murder.get("responsible_actor_id") is None:
            murder.pop("responsible_actor_id", None)
        for event in document["timeline"]:
            if event.get("causal_role") is None:
                event.pop("causal_role", None)
            if not event.get("dependency_event_ids"):
                event.pop("dependency_event_ids", None)
            if event.get("means_id") is None:
                event.pop("means_id", None)
            if event.get("requires_actor_victim_colocation") is False:
                event.pop("requires_actor_victim_colocation", None)
            if event.get("victim_encounters_means") is False:
                event.pop("victim_encounters_means", None)
    # Generated evidence retains explicit causal provenance. Preserve authored
    # foundation fingerprints when the backwards-compatible optional field is
    # absent, while generated cases keep it in canonical truth.
    for evidence in document["evidence"].values():
        if evidence.get("provenance") is None:
            evidence.pop("provenance", None)
    # Evidence routes were added after the authored foundation was tagged. Keep
    # the legacy authored fingerprint byte-stable when that optional field is
    # empty, while generated cases retain their proof routes in canonical truth.
    if not document["solution"].get("evidence_routes"):
        document["solution"].pop("evidence_routes", None)
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def character_card_fingerprint(card: GameCharacterCard) -> str:
    """Hash canonical validated CCv3 JSON, independent of file formatting."""

    payload = json.dumps(
        card.model_dump(mode="json"),
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


def _load_model(
    path: Path,
    model_type: type[CaseRecipe | CaseDefinition | LocationPackage | GameCharacterCard],
):
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

    # Spine selection remains on the original v1 domain so adding cast metadata
    # never changes which authored mystery an existing seed resolves to.
    material = f"case-recipe-v1:{recipe.id}:1:{seed}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % len(recipe.case_ids)


def _selected_character_index(recipe: CaseRecipe, seed: int, slot_id: str) -> int:
    material = (
        f"case-recipe-cast-v1:{recipe.id}:{recipe.schema_version}:{seed}:{slot_id}"
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % 3


def _load_and_validate_cards(
    recipe: CaseRecipe,
    *,
    characters_dir: Path,
) -> dict[str, GameCharacterCard]:
    cards: dict[str, GameCharacterCard] = {}
    for slot in recipe.cast_slots:
        for character_id in slot.candidate_card_ids:
            card = _load_model(
                _document_path(characters_dir, character_id), GameCharacterCard
            )
            assert isinstance(card, GameCharacterCard)
            compatible_slots = (
                card.data.extensions.murder_mystery.compatible_case_slots
            )
            if compatible_slots and slot.id not in compatible_slots:
                raise RecipeValidationError(
                    f"character {character_id!r} is not compatible with slot {slot.id!r}"
                )
            actual_fingerprint = character_card_fingerprint(card)
            if actual_fingerprint != recipe.card_fingerprints[character_id]:
                raise RecipeValidationError(
                    f"character {character_id!r} fingerprint does not match recipe"
                )
            cards[character_id] = card
    return cards


_NAME_TITLES = {
    "captain",
    "chef",
    "commander",
    "countess",
    "dr",
    "dr.",
    "inspector",
    "lady",
    "major",
}


def _name_parts(name: str) -> tuple[str, str, str]:
    """Return given name, surname, and optional title for authored cast names."""

    words = name.split()
    has_title = bool(words and words[0].lower() in _NAME_TITLES)
    title = words[0] if has_title else ""
    personal = words[1:] if has_title else words
    if len(personal) < 2:
        return personal[0] if personal else name, "", title
    return personal[0], " ".join(personal[1:]), title


def _name_replacements(
    slot_card_ids: dict[str, str],
    cards: dict[str, GameCharacterCard],
    source_cards: dict[str, GameCharacterCard],
) -> tuple[tuple[str, str], ...]:
    replacements: dict[str, str] = {}
    for slot_id, selected_id in slot_card_ids.items():
        if slot_id == selected_id:
            continue
        source = source_cards[slot_id].data.name
        target = cards[selected_id].data.name
        source_given, source_surname, source_title = _name_parts(source)
        target_given, target_surname, target_title = _name_parts(target)
        replacements[source] = target
        replacements[source_given] = target_given
        if source_surname and target_surname:
            replacements[source_surname] = target_surname
        if source_title and source_given and target_given:
            titled_given = " ".join(
                part for part in (target_title, target_given) if part
            )
            replacements[f"{source_title} {source_given}"] = titled_given
            if source_title.lower().rstrip(".") == "dr":
                replacements[f"Dr {source_given}"] = " ".join(
                    part
                    for part in (target_title.rstrip("."), target_given)
                    if part
                )
                replacements[f"Dr. {source_given}"] = titled_given
        if source_title and source_surname and target_surname:
            replacements[f"{source_title} {source_surname}"] = " ".join(
                part for part in (target_title, target_surname) if part
            )
            if source_title.lower().rstrip(".") == "dr":
                replacements[f"Dr {source_surname}"] = " ".join(
                    part for part in (target_title.rstrip("."), target_surname) if part
                )
                replacements[f"Dr. {source_surname}"] = " ".join(
                    part for part in (target_title, target_surname) if part
                )
    return tuple(sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True))


def _materialize_case(
    template: CaseDefinition,
    slot_card_ids: dict[str, str],
    cards: dict[str, GameCharacterCard],
    source_cards: dict[str, GameCharacterCard],
    location: LocationPackage,
) -> CaseDefinition:
    """Project logical template IDs and explicit authored name references onto a cast."""

    name_replacements = _name_replacements(slot_card_ids, cards, source_cards)

    def remap(value: object) -> object:
        if isinstance(value, dict):
            return {
                slot_card_ids.get(key, key): remap(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [remap(item) for item in value]
        if isinstance(value, tuple):
            return [remap(item) for item in value]
        if not isinstance(value, str):
            return value
        if value in slot_card_ids:
            return slot_card_ids[value]
        if ":" in value:
            route, target = value.split(":", 1)
            if target in slot_card_ids:
                return f"{route}:{slot_card_ids[target]}"
        rendered = value
        for source, target in name_replacements:
            rendered = re.sub(
                rf"(?<![\w]){re.escape(source)}(?![\w])",
                target,
                rendered,
            )
        return rendered

    try:
        materialized = CaseDefinition.model_validate(remap(template.model_dump(mode="json")))
    except ValidationError as error:
        raise RecipeValidationError("materialized case does not match the case schema") from error
    report = validate_case(materialized, location)
    if not report.is_valid:
        raise RecipeValidationError("materialized case failed authored-content validation")
    return materialized


def _resolve_recipe_bundle(
    recipe_id: str,
    seed: int,
    *,
    assemblies_dir: Path,
    cases_dir: Path,
    locations_dir: Path,
    characters_dir: Path,
    selected_character_ids: Iterable[str] | None = None,
) -> tuple[CaseRecipeSelection, CaseDefinition]:
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
    template = cases[selected_case_id]
    if not recipe.cast_slots:
        if selected_character_ids is not None:
            raise RecipeValidationError("this recipe does not support manual cast selection")
        return (
            CaseRecipeSelection(
                recipe_id=recipe.id,
                schema_version=recipe.schema_version,
                seed=validated_seed,
                selected_case_id=selected_case_id,
                content_fingerprint=case_content_fingerprint(template),
            ),
            template,
        )

    template_cast = set(template.character_ids)
    slots_by_id = {slot.id: slot for slot in recipe.cast_slots}
    if set(slots_by_id) != template_cast:
        raise RecipeValidationError("character slots must match the complete template cast")
    for case_id, candidate_case in cases.items():
        if set(candidate_case.character_ids) != template_cast:
            raise RecipeValidationError(
                f"case {case_id!r} does not use the recipe character slots"
            )
    cards = _load_and_validate_cards(recipe, characters_dir=characters_dir)
    source_cards: dict[str, GameCharacterCard] = {}
    for slot_id in sorted(slots_by_id):
        source_path = characters_dir / f"{slot_id}.json"
        if not source_path.is_file():
            source_path = CHARACTER_CARDS_DIR / f"{slot_id}.json"
        source_card = _load_model(source_path, GameCharacterCard)
        assert isinstance(source_card, GameCharacterCard)
        source_cards[slot_id] = source_card
    cast_mode: Literal["automatic", "manual"] = "automatic"
    if selected_character_ids is None:
        slot_card_ids = {
            slot_id: slot.candidate_card_ids[
                _selected_character_index(recipe, validated_seed, slot_id)
            ]
            for slot_id, slot in sorted(slots_by_id.items())
        }
    else:
        selected = tuple(selected_character_ids)
        if len(selected) != 8 or any(
            not isinstance(character_id, str) for character_id in selected
        ):
            raise RecipeValidationError("a manual cast must contain exactly eight unique character IDs")
        if len(set(selected)) != 8:
            raise RecipeValidationError("a manual cast must contain exactly eight unique character IDs")
        selected_set = set(selected)
        all_candidates = set(cards)
        if not selected_set <= all_candidates:
            raise RecipeValidationError("manual cast contains an unknown character ID")
        slot_card_ids = {}
        for slot_id, slot in sorted(slots_by_id.items()):
            matches = selected_set & set(slot.candidate_card_ids)
            if len(matches) != 1:
                raise RecipeValidationError(
                    "manual cast must choose one compatible character from each ensemble group"
                )
            slot_card_ids[slot_id] = matches.pop()
        cast_mode = "manual"
    materialized = _materialize_case(
        template, slot_card_ids, cards, source_cards, location
    )
    selected_ids = set(slot_card_ids.values())
    selection = CaseRecipeSelection(
        recipe_id=recipe.id,
        schema_version=recipe.schema_version,
        seed=validated_seed,
        selected_case_id=selected_case_id,
        content_fingerprint=case_content_fingerprint(materialized),
        cast_mode=cast_mode,
        slot_card_ids=slot_card_ids,
        card_fingerprints={
            character_id: recipe.card_fingerprints[character_id]
            for character_id in sorted(selected_ids)
        },
    )
    return selection, materialized


def resolve_case_recipe(
    recipe_id: str,
    seed: int,
    *,
    assemblies_dir: Path = ASSEMBLIES_DIR,
    cases_dir: Path = CASES_DIR,
    locations_dir: Path = LOCATIONS_DIR,
    characters_dir: Path = CHARACTER_CARDS_DIR,
    selected_character_ids: Iterable[str] | None = None,
) -> CaseRecipeSelection:
    """Validate every named case, then select one reproducibly for ``seed``.

    Validation intentionally happens before selection, so a broken or tampered
    non-selected case can never hide inside a recipe.
    """

    selection, _ = _resolve_recipe_bundle(
        recipe_id,
        seed,
        assemblies_dir=assemblies_dir,
        cases_dir=cases_dir,
        locations_dir=locations_dir,
        characters_dir=characters_dir,
        selected_character_ids=selected_character_ids,
    )
    return selection


def materialize_case_recipe(
    selection: CaseRecipeSelection,
    *,
    assemblies_dir: Path = ASSEMBLIES_DIR,
    cases_dir: Path = CASES_DIR,
    locations_dir: Path = LOCATIONS_DIR,
    characters_dir: Path = CHARACTER_CARDS_DIR,
) -> CaseDefinition:
    """Rebuild an exact selected case and reject stale or tampered metadata."""

    resolved, materialized = _resolve_recipe_bundle(
        selection.recipe_id,
        selection.seed,
        assemblies_dir=assemblies_dir,
        cases_dir=cases_dir,
        locations_dir=locations_dir,
        characters_dir=characters_dir,
        selected_character_ids=(
            selection.slot_card_ids.values() if selection.cast_mode == "manual" else None
        ),
    )
    if resolved != selection:
        raise RecipeValidationError("recipe selection is not reproducible")
    return materialized


def resolve_materialized_case_recipe(
    recipe_id: str,
    seed: int,
    *,
    assemblies_dir: Path = ASSEMBLIES_DIR,
    cases_dir: Path = CASES_DIR,
    locations_dir: Path = LOCATIONS_DIR,
    characters_dir: Path = CHARACTER_CARDS_DIR,
    selected_character_ids: Iterable[str] | None = None,
) -> tuple[CaseRecipeSelection, CaseDefinition]:
    """Resolve selection metadata and its validated runnable case in one pass."""

    return _resolve_recipe_bundle(
        recipe_id,
        seed,
        assemblies_dir=assemblies_dir,
        cases_dir=cases_dir,
        locations_dir=locations_dir,
        characters_dir=characters_dir,
        selected_character_ids=selected_character_ids,
    )
