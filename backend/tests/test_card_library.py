"""Adversarial coverage for the isolated CCv3 card-library workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from game.card_library import (
    MAX_CARD_BYTES,
    CardLibraryError,
    export_card_json,
    inspect_card_draft,
    safe_card_path,
    write_card_draft,
)
from game.content import load_character_card


@pytest.fixture
def valid_document() -> dict[str, object]:
    return load_character_card("zara_okonkwo").model_dump(mode="json")


def test_one_empty_and_million_byte_inputs_are_rejected(valid_document: dict[str, object]) -> None:
    assert not inspect_card_draft("{").ok
    assert not inspect_card_draft("").ok
    assert not inspect_card_draft(b"x" * (MAX_CARD_BYTES + 1)).ok
    assert inspect_card_draft(json.dumps(valid_document)).ok


def test_requires_json_object_ccv3_header_and_playable_extension(valid_document: dict[str, object]) -> None:
    assert not inspect_card_draft("[]").ok

    wrong_spec = dict(valid_document)
    wrong_spec["spec_version"] = "2.0"
    assert not inspect_card_draft(wrong_spec).ok

    data = dict(valid_document["data"])  # type: ignore[arg-type]
    data["extensions"] = {}
    no_extension = dict(valid_document, data=data)
    assert not inspect_card_draft(no_extension).ok


def test_malformed_duplicate_and_extra_fields_are_rejected(valid_document: dict[str, object]) -> None:
    assert not inspect_card_draft('{"spec":"chara_card_v3","spec":"chara_card_v3"}').ok
    extra = dict(valid_document, unauthorized=True)
    assert not inspect_card_draft(extra).ok


def test_preview_does_not_disclose_prompt_or_lore(valid_document: dict[str, object]) -> None:
    data = dict(valid_document["data"])  # type: ignore[arg-type]
    data["system_prompt"] = "DO NOT LEAK: the murderer is somebody"
    data["character_book"] = {"entries": [{"keys": ["x"], "content": "secret", "enabled": True, "insertion_order": 1, "use_regex": False}]}
    result = inspect_card_draft(dict(valid_document, data=data))

    assert result.ok and result.preview
    preview_text = result.preview.model_dump_json()
    assert "DO NOT LEAK" not in preview_text
    assert "secret" not in preview_text


def test_paths_reserved_names_and_collisions_are_rejected(tmp_path: Path, valid_document: dict[str, object]) -> None:
    result = inspect_card_draft(valid_document, character_id="safe_card")
    assert result.ok and result.card
    for unsafe in ("../escape", "safe/card", "safe.json", "CON", "characters"):
        with pytest.raises(CardLibraryError):
            safe_card_path(tmp_path, unsafe)

    destination = write_card_draft(tmp_path, "safe_card", result.card)
    assert destination.name == "safe_card.json"
    with pytest.raises(CardLibraryError, match="already exists"):
        write_card_draft(tmp_path, "safe_card", result.card)
    assert write_card_draft(tmp_path, "safe_card", result.card, replace=True) == destination


def test_round_trip_export_is_valid_json_and_revalidates(valid_document: dict[str, object]) -> None:
    imported = inspect_card_draft(valid_document)
    assert imported.ok and imported.card
    payload = export_card_json(imported.card)
    repeated = inspect_card_draft(payload)
    assert repeated.ok and repeated.card == imported.card


def test_failed_atomic_replace_preserves_previous_draft(
    tmp_path: Path, valid_document: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    imported = inspect_card_draft(valid_document)
    assert imported.ok and imported.card
    destination = write_card_draft(tmp_path, "safe_card", imported.card)
    before = destination.read_bytes()

    def fail_replace(source: str, target: Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("game.card_library.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        write_card_draft(tmp_path, "safe_card", imported.card, replace=True)

    assert destination.read_bytes() == before
    assert not list(tmp_path.glob(".card-*.tmp"))
