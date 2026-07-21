"""Adversarial tests for the bounded, non-authoritative story director."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from game.content import load_case, load_character_card, load_location
from game.engine import GameEngine
from game.persistence import restore_engine, snapshot_engine
from game.story_director import fallback_story_presentation, generate_story_presentation


class FakeDirectorLLM:
    def __init__(self, outputs: list[str | Exception]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, object]] = []

    async def generate(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(content=output)


def _case_and_location():
    return load_case("ashwick_sample"), load_location("ashwick_manor")


def _valid_director_document(case, location) -> dict[str, object]:
    return {
        "title": "The Glass Hour",
        "tagline": "A storm seals eight uneasy lives inside Ashwick Manor.",
        "public_opening": "Thunder folds around the manor as the guests gather beneath the old clock.",
        "atmosphere": "Wet stone, dim lamps, and polite voices sharpen every silence.",
        "character_tensions": [
            {
                "character_id": character_id,
                "public_hook": "Maintains a careful composure whenever the room falls quiet.",
            }
            for character_id in case.character_ids
        ],
        "room_flavour": [
            {
                "room_id": room_id,
                "text": f"A new hush settles over {room.name}.",
            }
            for room_id, room in location.rooms.items()
        ],
    }


@pytest.mark.asyncio
async def test_valid_director_response_changes_only_public_presentation() -> None:
    case, location = _case_and_location()
    document = _valid_director_document(case, location)
    llm = FakeDirectorLLM([json.dumps(document)])

    patch = await generate_story_presentation(llm, case, location)
    engine = GameEngine(case, location, story_presentation=patch)
    view = engine.view()

    assert patch.source == "llm"
    assert patch.title == "The Glass Hour"
    assert patch.public_opening == document["public_opening"]
    assert dict((item.character_id, item.public_hook) for item in patch.character_tensions) == {
        item["character_id"]: item["public_hook"]
        for item in document["character_tensions"]
    }
    assert dict((item.room_id, item.text) for item in patch.room_flavour) == {
        item["room_id"]: item["text"] for item in document["room_flavour"]
    }
    assert view.case_title == document["title"]
    assert view.story.public_opening == document["public_opening"]
    assert view.story.character_tensions == {
        item["character_id"]: item["public_hook"]
        for item in document["character_tensions"]
    }
    assert engine.case.murder == case.murder
    assert engine.case.solution == case.solution
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_director_prompt_shares_only_public_scaffolding() -> None:
    case, location = _case_and_location()
    llm = FakeDirectorLLM([json.dumps(_valid_director_document(case, location))])

    await generate_story_presentation(llm, case, location)

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    public_payload = messages[1].content
    for forbidden in (
        "murderer_id",
        "private_motive",
        '"solution"',
        '"evidence"',
        case.murder.cover_story,
        case.overlays[case.murder.murderer_id].private_motive,
    ):
        assert forbidden not in public_payload
    # Every selected card is public, including the eventual culprit; the secret
    # is their role, not their identity as a person in the cast.
    assert case.murder.murderer_id in public_payload
    assert case.murder.victim_id in public_payload
    assert llm.calls[0]["json_mode"] is True
    assert llm.calls[0]["temperature"] == 0.2


def _duplicate_tension_document(case, location) -> dict[str, object]:
    document = _valid_director_document(case, location)
    tensions = document["character_tensions"]
    assert isinstance(tensions, list)
    tensions[-1] = dict(tensions[0])
    return document


def _missing_tension_document(case, location) -> dict[str, object]:
    document = _valid_director_document(case, location)
    tensions = document["character_tensions"]
    assert isinstance(tensions, list)
    document["character_tensions"] = tensions[:-1]
    return document


def _unknown_id_document(case, location) -> dict[str, object]:
    document = _valid_director_document(case, location)
    tensions = document["character_tensions"]
    assert isinstance(tensions, list)
    tensions[0]["character_id"] = "not_selected"
    return document


def _duplicate_room_document(case, location) -> dict[str, object]:
    document = _valid_director_document(case, location)
    rooms = document["room_flavour"]
    assert isinstance(rooms, list)
    rooms[-1] = dict(rooms[0])
    return document


def _missing_room_document(case, location) -> dict[str, object]:
    document = _valid_director_document(case, location)
    rooms = document["room_flavour"]
    assert isinstance(rooms, list)
    document["room_flavour"] = rooms[:-1]
    return document


def _oversized_document(case, location) -> dict[str, object]:
    document = _valid_director_document(case, location)
    document["title"] = "x" * 121
    return document


def _extra_field_document(case, location) -> dict[str, object]:
    document = _valid_director_document(case, location)
    document["murderer_id"] = case.murder.murderer_id
    return document


def _culprit_spoiler_document(case, location) -> dict[str, object]:
    document = _valid_director_document(case, location)
    culprit_name = load_character_card(case.murder.murderer_id).data.name
    document["public_opening"] = f"{culprit_name} killed the host before the alarm."
    return document


def _invented_evidence_document(case, location) -> dict[str, object]:
    document = _valid_director_document(case, location)
    rooms = document["room_flavour"]
    assert isinstance(rooms, list)
    rooms[0]["text"] = "A bloody knife lies beneath the window."
    return document


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_document",
    [
        lambda case, location: "{not json",
        _unknown_id_document,
        _duplicate_tension_document,
        _missing_tension_document,
        _duplicate_room_document,
        _missing_room_document,
        _oversized_document,
        _extra_field_document,
        _culprit_spoiler_document,
        _invented_evidence_document,
    ],
)
async def test_bad_director_output_retries_once_then_uses_fallback(invalid_document) -> None:
    case, location = _case_and_location()
    invalid = invalid_document(case, location)
    raw = invalid if isinstance(invalid, str) else json.dumps(invalid)
    llm = FakeDirectorLLM([raw, raw])

    patch = await generate_story_presentation(llm, case, location)

    assert patch.source == "fallback"
    assert len(llm.calls) == 2
    assert patch.title == case.title


@pytest.mark.asyncio
async def test_provider_errors_retry_once_then_use_fallback() -> None:
    case, location = _case_and_location()
    llm = FakeDirectorLLM([RuntimeError("network down"), RuntimeError("still down")])

    patch = await generate_story_presentation(llm, case, location)

    assert patch.source == "fallback"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_missing_provider_immediately_uses_fallback() -> None:
    case, location = _case_and_location()

    patch = await generate_story_presentation(None, case, location)

    assert patch.source == "fallback"
    assert patch.title == case.title
    assert {item.character_id for item in patch.character_tensions} == set(case.character_ids)
    assert {item.room_id for item in patch.room_flavour} == set(location.rooms)


@pytest.mark.asyncio
async def test_story_presentation_round_trips_in_a_save_but_not_a_public_view() -> None:
    case, location = _case_and_location()
    document = _valid_director_document(case, location)
    patch = await generate_story_presentation(
        FakeDirectorLLM([json.dumps(document)]), case, location
    )
    engine = GameEngine(case, location, story_presentation=patch)

    envelope = snapshot_engine(engine)
    restored = restore_engine(envelope.model_dump(mode="json"), case, location)
    public_view = restored.view().model_dump(mode="json")

    assert restored.story_presentation == patch
    assert restored.view().story.public_opening == document["public_opening"]
    assert envelope.story_presentation == patch
    serialized_public = json.dumps(public_view).lower()
    assert "base_case_fingerprint" not in serialized_public
    assert patch.base_case_fingerprint not in serialized_public


def test_engine_revalidates_story_patch_at_the_consumer_boundary() -> None:
    case, location = _case_and_location()
    safe = fallback_story_presentation(case, location)
    wrong_case = safe.model_copy(update={"base_case_fingerprint": "0" * 64})
    unsafe = safe.model_copy(
        update={"public_opening": "The murderer left bloody evidence beside the body."}
    )

    with pytest.raises(ValueError):
        GameEngine(case, location, story_presentation=wrong_case)
    with pytest.raises(ValueError):
        GameEngine(case, location, story_presentation=unsafe)
