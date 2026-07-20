"""Load validated authored content for the turn-based game."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from game.models import CaseDefinition, GameCharacterCard, LocationPackage


CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
LOCATIONS_DIR = CONTENT_DIR / "locations"
CASES_DIR = CONTENT_DIR / "cases"
CHARACTER_CARDS_DIR = CONTENT_DIR / "characters"

ModelT = TypeVar("ModelT", bound=BaseModel)


def _load_json_model(path: Path, model_type: type[ModelT]) -> ModelT:
    """Load one UTF-8 JSON document and validate it as ``model_type``."""
    with path.open("r", encoding="utf-8") as handle:
        return model_type.model_validate(json.load(handle))


def _document_path(directory: Path, document_id: str) -> Path:
    """Resolve a safe content ID below ``directory``."""
    if not document_id or Path(document_id).name != document_id:
        raise ValueError(f"invalid content ID: {document_id!r}")
    path = directory / f"{document_id}.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_location(location_id: str) -> LocationPackage:
    return _load_json_model(
        _document_path(LOCATIONS_DIR, location_id), LocationPackage
    )


def load_case(case_id: str) -> CaseDefinition:
    return _load_json_model(_document_path(CASES_DIR, case_id), CaseDefinition)


def load_character_card(character_id: str) -> GameCharacterCard:
    return _load_json_model(
        _document_path(CHARACTER_CARDS_DIR, character_id), GameCharacterCard
    )


def list_content_ids(directory: Path) -> list[str]:
    """Return deterministic IDs for every JSON document in a content directory."""
    return sorted(path.stem for path in directory.glob("*.json") if path.is_file())
