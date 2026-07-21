"""Bounded AI story direction over an already-valid authoritative mystery.

The director may rewrite public presentation, never the culprit, schedules,
evidence graph, rooms, or solution. Invalid provider output falls back to a
deterministic authored presentation so starting a game never requires a key.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Literal

from pydantic import Field

from game.content import load_character_card
from game.models import CaseDefinition, FrozenModel, LocationPackage
from game.recipes import case_content_fingerprint


class StoryCharacterTension(FrozenModel):
    character_id: str
    public_hook: str = Field(min_length=1, max_length=320)


class StoryRoomFlavour(FrozenModel):
    room_id: str
    text: str = Field(min_length=1, max_length=400)


class StoryPresentationDraft(FrozenModel):
    title: str = Field(min_length=1, max_length=120)
    tagline: str = Field(min_length=1, max_length=240)
    public_opening: str = Field(min_length=1, max_length=1_600)
    atmosphere: str = Field(min_length=1, max_length=1_200)
    character_tensions: tuple[StoryCharacterTension, ...] = Field(min_length=8, max_length=8)
    room_flavour: tuple[StoryRoomFlavour, ...] = Field(min_length=1, max_length=32)


class StoryPresentationPatch(StoryPresentationDraft):
    schema_version: Literal[1] = 1
    base_case_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal["llm", "fallback"]


class StoryGenerationError(ValueError):
    """Provider output was malformed or referenced unauthorized content."""


_HIGH_RISK_STORY_LANGUAGE = re.compile(
    r"\b(?:"
    r"accus(?:e|ed|es|ing|ation)|alibi|blood(?:y|stained)?|clue|culprit|"
    r"evidence|forg(?:e|ed|ery)|guilt(?:y)?|kill(?:ed|er|ing|s)?|knife|"
    r"motive|murder(?:ed|er|ess|ing)?|pistol|poison(?:ed|ing)?|poker|"
    r"shoot(?:ing|s)?|shot|stab(?:bed|bing|s)?|strangl(?:e|ed|ing)|"
    r"suspect|weapon|wound(?:ed|s)?"
    r")\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z0-9]+")


def _story_text(patch: StoryPresentationPatch) -> tuple[str, ...]:
    return (
        patch.title,
        patch.tagline,
        patch.public_opening,
        patch.atmosphere,
        *(item.public_hook for item in patch.character_tensions),
        *(item.text for item in patch.room_flavour),
    )


def _private_case_strings(case: CaseDefinition) -> tuple[str, ...]:
    """Collect authored truth that public director prose must never reproduce."""

    strings = [
        case.murder.method.replace("_", " "),
        case.murder.weapon_id.replace("_", " "),
        case.murder.means,
        case.murder.motive,
        case.murder.opportunity,
        case.murder.cover_story,
        *(fact.statement for fact in case.facts.values()),
        *(event.summary for event in case.timeline),
        case.opening.body_condition,
        *case.opening.discoverer_observations,
        *case.opening.initial_reactions.values(),
    ]
    for overlay in case.overlays.values():
        strings.extend(
            (
                overlay.private_motive,
                overlay.alibi_claim,
                *overlay.secrets,
                *overlay.goals,
                *(entry.activity for entry in overlay.schedule),
                *(observation.summary for observation in overlay.observations),
                *(lie.claim for lie in overlay.lies),
                *(lie.reason for lie in overlay.lies),
                *(relationship.private_summary for relationship in overlay.relationships),
            )
        )
    for evidence in case.evidence.values():
        strings.extend(
            (evidence.name, evidence.description, evidence.red_herring_explanation)
        )
    return tuple(value for value in strings if value)


def _validate_public_language(
    patch: StoryPresentationPatch,
    case: CaseDefinition,
    location: LocationPackage,
) -> None:
    fragments = _story_text(patch)
    if any(_HIGH_RISK_STORY_LANGUAGE.search(fragment) for fragment in fragments):
        raise StoryGenerationError("story presentation contains investigative claims")

    # A surviving character's name in generated prose can turn an otherwise
    # atmospheric sentence into an accusation. Character hooks are already
    # keyed to their public card, so names and raw IDs are unnecessary there.
    for character_id in case.character_ids:
        if character_id == case.murder.victim_id:
            continue
        name = load_character_card(character_id).data.name.casefold()
        for fragment in fragments:
            rendered = fragment.casefold()
            if name in rendered or character_id.casefold() in rendered:
                raise StoryGenerationError(
                    "story presentation must not name a surviving character in prose"
                )

    private_strings = _private_case_strings(case)
    normalized_story = " ".join(" ".join(fragment.casefold().split()) for fragment in fragments)
    for private_text in private_strings:
        normalized_private = " ".join(private_text.casefold().split())
        if len(normalized_private) >= 16 and normalized_private in normalized_story:
            raise StoryGenerationError("story presentation reproduces private case truth")

    # Reject distinctive hidden vocabulary even when the provider paraphrases
    # a longer sentence. Public payload words (including room descriptions and
    # public relationships) remain available for ordinary atmospheric prose.
    public_words = set(
        _WORD.findall(
            json.dumps(
                _safe_director_payload(case, location),
                ensure_ascii=False,
            ).casefold()
        )
    )
    private_word_counts = Counter(
        _WORD.findall(" ".join(private_strings).casefold())
    )
    distinctive_private_words = {
        word
        for word, count in private_word_counts.items()
        if count >= 2 and len(word) >= 9 and word not in public_words
    }
    story_words = set(_WORD.findall(" ".join(fragments).casefold()))
    if story_words & distinctive_private_words:
        raise StoryGenerationError("story presentation uses private case vocabulary")


def validate_story_presentation(
    patch: StoryPresentationPatch,
    case: CaseDefinition,
    location: LocationPackage,
) -> StoryPresentationPatch:
    if patch.base_case_fingerprint != case_content_fingerprint(case):
        raise StoryGenerationError("story presentation belongs to a different case")
    tension_ids = [item.character_id for item in patch.character_tensions]
    if len(tension_ids) != len(set(tension_ids)) or set(tension_ids) != set(case.character_ids):
        raise StoryGenerationError("story presentation must cover the selected cast exactly")
    room_ids = [item.room_id for item in patch.room_flavour]
    if len(room_ids) != len(set(room_ids)) or set(room_ids) != set(location.rooms):
        raise StoryGenerationError("story presentation must cover the authored rooms exactly")
    _validate_public_language(patch, case, location)
    return patch


def fallback_story_presentation(
    case: CaseDefinition,
    location: LocationPackage,
) -> StoryPresentationPatch:
    """Build a complete public presentation without calling a provider."""

    victim_name = load_character_card(case.murder.victim_id).data.name
    return validate_story_presentation(
        StoryPresentationPatch(
            base_case_fingerprint=case_content_fingerprint(case),
            source="fallback",
            title=case.title,
            tagline=f"A death at {location.name}. Eight lives are bound to one impossible night.",
            public_opening=(
                f"The alarm has already sounded. {victim_name} is dead, the exits are closed, "
                "and every surviving guest carries a private version of the evening."
            ),
            atmosphere=f"{location.description} {location.isolation_premise}",
            character_tensions=tuple(
                StoryCharacterTension(
                    character_id=character_id,
                    public_hook=case.overlays[character_id].public_relationship_to_victim,
                )
                for character_id in case.character_ids
            ),
            room_flavour=tuple(
                StoryRoomFlavour(room_id=room_id, text=room.description)
                for room_id, room in location.rooms.items()
            ),
        ),
        case,
        location,
    )


def _safe_director_payload(case: CaseDefinition, location: LocationPackage) -> dict[str, Any]:
    """Expose enough public scaffolding to direct tone without sharing solution truth."""

    cast = []
    for character_id in case.character_ids:
        card = load_character_card(character_id)
        extension = card.data.extensions.murder_mystery
        cast.append(
            {
                "character_id": character_id,
                "name": card.data.name,
                "description": card.data.description,
                "public_biography": extension.public_biography,
                "speaking_style": extension.speaking_style,
                "public_relationship_to_victim": case.overlays[
                    character_id
                ].public_relationship_to_victim,
            }
        )
    return {
        "base_case_fingerprint": case_content_fingerprint(case),
        "location": {
            "id": location.id,
            "name": location.name,
            "description": location.description,
            "isolation_premise": location.isolation_premise,
            "rooms": [
                {"room_id": room_id, "name": room.name, "description": room.description}
                for room_id, room in location.rooms.items()
            ],
        },
        "victim_id": case.murder.victim_id,
        "cast": cast,
    }


async def generate_story_presentation(
    llm: Any | None,
    case: CaseDefinition,
    location: LocationPackage,
) -> StoryPresentationPatch:
    """Ask the configured backend model for bounded public prose, or fall back."""

    fallback = fallback_story_presentation(case, location)
    if llm is None:
        return fallback
    from llm.client import LLMMessage

    system = (
        "You are the story director for a closed-circle murder mystery. Return one JSON object "
        "with exactly: title, tagline, public_opening, atmosphere, character_tensions, room_flavour. "
        "character_tensions must contain exactly one {character_id, public_hook} for every supplied "
        "character. room_flavour must contain exactly one {room_id, text} for every supplied room. "
        "Use only supplied IDs, people, rooms, and public relationships. Never identify or hint at "
        "the murderer, invent evidence, change the victim, add rooms, assert unseen facts, or include "
        "private instructions. Do not write character names or raw character IDs inside prose; each "
        "public_hook is already attached to its character_id. Avoid investigative claims, weapons, "
        "methods, wounds, alibis, clues, accusations, guilt, or culprit language. The engine already "
        "owns the mystery truth; you generate its distinct public title, atmosphere, opening, and "
        "surface-level social framing. JSON only."
    )
    payload = json.dumps(_safe_director_payload(case, location), ensure_ascii=False)
    for _attempt in range(2):
        try:
            response = await llm.generate(
                [
                    LLMMessage(role="system", content=system),
                    LLMMessage(role="user", content=payload),
                ],
                max_tokens=4_096,
                temperature=0.2,
                json_mode=True,
            )
            draft = StoryPresentationDraft.model_validate(json.loads(response.content))
            patch = StoryPresentationPatch(
                **draft.model_dump(mode="python"),
                base_case_fingerprint=case_content_fingerprint(case),
                source="llm",
            )
            return validate_story_presentation(patch, case, location)
        # Provider adapters are untrusted boundaries. Cancellation still
        # propagates because asyncio.CancelledError derives from BaseException.
        except Exception:
            continue
    return fallback
