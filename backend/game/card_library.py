"""Safe, local JSON Character Card v3 draft handling.

This module is deliberately independent from the game service and HTTP routes.
It accepts cards as *data*, validates the playable game extension, and writes
only an atomically replaced JSON file under a caller-controlled library root.
Nothing in this module evaluates ``system_prompt``, lorebook content, or any
other imported text.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Mapping

from pydantic import Field, ValidationError

from game.models import GameCharacterCard, StrictModel


MAX_CARD_BYTES = 512 * 1024
"""Largest accepted JSON card document, before parsing."""

_CARD_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul", "clock$",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_LIBRARY_RESERVED = {"characters", "cases", "locations", "drafts", "assets", "index"}


class CardLibraryError(ValueError):
    """A card draft cannot safely be inspected, exported, or stored."""


class CardValidationIssue(StrictModel):
    """A stable, display-safe validation issue for an editor/API caller."""

    code: str
    message: str


class CardPreview(StrictModel):
    """Player/editor-safe metadata intentionally excluding prompts and lore."""

    character_id: str
    name: str
    description: str
    tags: tuple[str, ...]
    creator: str
    character_version: str
    playable: bool = True


class CardImportResult(StrictModel):
    """Result of parsing an untrusted draft without persisting it."""

    ok: bool
    card: GameCharacterCard | None = None
    preview: CardPreview | None = None
    issues: tuple[CardValidationIssue, ...] = Field(default_factory=tuple)


def _issue(code: str, message: str) -> CardImportResult:
    return CardImportResult(
        ok=False, issues=(CardValidationIssue(code=code, message=message),)
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _raw_json_object(raw: str | bytes | bytearray | Mapping[str, Any]) -> Mapping[str, Any]:
    """Decode exactly one bounded JSON object, rejecting duplicate keys."""

    if isinstance(raw, Mapping):
        try:
            encoded = json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise CardLibraryError("card object is not JSON-serializable") from error
        if len(encoded) > MAX_CARD_BYTES:
            raise CardLibraryError("card document exceeds the maximum size")
        # A JSON round trip also normalizes mapping subclasses and prevents an
        # arbitrary mapping object from reaching Pydantic internals.
        decoded = json.loads(encoded.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    else:
        if isinstance(raw, str):
            try:
                encoded = raw.encode("utf-8")
            except UnicodeEncodeError as error:
                raise CardLibraryError("card text is not valid UTF-8") from error
        elif isinstance(raw, (bytes, bytearray)):
            encoded = bytes(raw)
        else:
            raise CardLibraryError("card must be JSON text, bytes, or an object")
        if not encoded:
            raise CardLibraryError("card document is empty")
        if len(encoded) > MAX_CARD_BYTES:
            raise CardLibraryError("card document exceeds the maximum size")
        try:
            decoded = json.loads(encoded.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise CardLibraryError("card document is not valid JSON") from error

    if not isinstance(decoded, dict):
        raise CardLibraryError("card document must be a JSON object")
    return decoded


def derive_character_id(name: str) -> str:
    """Derive a portable, canonical ID from a card name."""

    if not isinstance(name, str):
        raise CardLibraryError("card name cannot be used to derive an ID")
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    candidate = re.sub(r"[^a-z0-9]+", "_", ascii_name.casefold()).strip("_")
    candidate = candidate[:64].rstrip("_")
    if not _CARD_ID_RE.fullmatch(candidate) or candidate in _WINDOWS_RESERVED | _LIBRARY_RESERVED:
        raise CardLibraryError("card name cannot be used to derive a safe character ID")
    return candidate


def validate_character_id(character_id: str) -> str:
    """Accept only a canonical single-file identifier, never a path."""

    if not isinstance(character_id, str) or not _CARD_ID_RE.fullmatch(character_id):
        raise CardLibraryError("character ID must be lowercase letters, digits, and underscores")
    if character_id in _WINDOWS_RESERVED | _LIBRARY_RESERVED:
        raise CardLibraryError("character ID is reserved")
    return character_id


def inspect_card_draft(
    raw: str | bytes | bytearray | Mapping[str, Any], *, character_id: str | None = None
) -> CardImportResult:
    """Validate a CCv3 game card and return only a spoiler-safe preview.

    A result always carries validation issues for malformed user input rather
    than making an editor parse Pydantic error structures.  The returned card
    remains inert data; no prompt or lorebook field is interpreted.
    """

    try:
        document = _raw_json_object(raw)
        card = GameCharacterCard.model_validate(document)
        resolved_id = (
            validate_character_id(character_id)
            if character_id is not None
            else derive_character_id(card.data.name)
        )
    except CardLibraryError as error:
        return _issue("invalid_document", str(error))
    except ValidationError as error:
        # The model's literals verify the genuine CCv3 header/version and its
        # required murder_mystery extension verifies game playability.
        message = error.errors(include_url=False)[0]["msg"] if error.errors() else "unsupported card"
        return _issue("invalid_card", message)

    return CardImportResult(
        ok=True,
        card=card,
        preview=CardPreview(
            character_id=resolved_id,
            name=card.data.name,
            description=card.data.description,
            tags=card.data.tags,
            creator=card.data.creator,
            character_version=card.data.character_version,
        ),
    )


def safe_card_path(library_root: Path | str, character_id: str) -> Path:
    """Return the normalized ``<id>.json`` destination below ``library_root``."""

    safe_id = validate_character_id(character_id)
    root = Path(library_root).resolve(strict=False)
    if root.exists() and not root.is_dir():
        raise CardLibraryError("card library root is not a directory")
    destination = (root / f"{safe_id}.json").resolve(strict=False)
    try:
        destination.relative_to(root)
    except ValueError as error:
        raise CardLibraryError("card path escapes the configured library root") from error
    return destination


def _validated_card(card: GameCharacterCard) -> GameCharacterCard:
    if not isinstance(card, GameCharacterCard):
        raise CardLibraryError("only a validated CCv3 card can be exported")
    try:
        return GameCharacterCard.model_validate(card.model_dump(mode="json"))
    except ValidationError as error:  # Defensive against future mutable models.
        raise CardLibraryError("card is no longer a valid playable CCv3 card") from error


def export_card_json(card: GameCharacterCard) -> bytes:
    """Serialize one validated card as JSON data, never PNG/CHARX payloads."""

    validated = _validated_card(card)
    payload = json.dumps(
        validated.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    if len(payload) > MAX_CARD_BYTES:
        raise CardLibraryError("validated card exceeds the maximum size")
    return payload


def write_card_draft(
    library_root: Path | str,
    character_id: str,
    card: GameCharacterCard,
    *,
    replace: bool = False,
) -> Path:
    """Atomically persist an already validated card inside a local library.

    Existing files require explicit replacement.  A failure before ``replace``
    leaves any existing draft intact and cleans up the temporary file.
    """

    destination = safe_card_path(library_root, character_id)
    payload = export_card_json(card)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=".card-", suffix=".tmp", delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary_name, destination)
        else:
            # ``exists()`` followed by replace is a time-of-check/time-of-use
            # race which could silently overwrite another editor's draft.
            # A same-directory hard link is an atomic create-if-absent.
            try:
                os.link(temporary_name, destination)
            except FileExistsError as error:
                raise CardLibraryError("a card draft with this ID already exists") from error
            Path(temporary_name).unlink()
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return destination
