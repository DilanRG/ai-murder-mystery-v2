"""Spoiler-safe static asset URLs exposed by the public game API."""

from __future__ import annotations

import re


_CHARACTER_ID = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def portrait_url(character_id: str) -> str:
    """Return the only character artwork URL the player-facing API may expose."""

    if not _CHARACTER_ID.fullmatch(character_id):
        raise ValueError(f"invalid character asset id: {character_id!r}")
    return f"/assets/characters/{character_id}/portrait-placeholder.svg"
