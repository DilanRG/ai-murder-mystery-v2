"""OpenRouter generation settings and public character card data."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from config.user_settings import get_user_config, save_user_config
from game.content import CHARACTER_CARDS_DIR, list_content_ids, load_character_card
from llm.client import LLMClient


router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(default=None, min_length=8, max_length=512)
    model: str | None = Field(default=None, min_length=1, max_length=240)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=0, le=1_000)
    max_tokens: int | None = Field(default=None, ge=1, le=65_536)
    autonomy: Literal["low", "high"] | None = None
    timer_mode: Literal["none", "realtime", "event"] | None = None
    timer_minutes: int | None = Field(default=None, ge=1, le=1_440)
    difficulty: Literal["easy", "normal", "hard"] | None = None


@router.get("/api/health")
async def health() -> dict[str, object]:
    from routers._deps import get_session

    session = get_session()
    config = get_user_config()
    return {
        "status": "ok",
        "llm_connected": bool(config.get("api_key")),
        "model": config.get("model", ""),
        "game_active": bool(session and session.is_active()),
    }


@router.get("/api/settings")
async def get_settings() -> dict[str, object]:
    config = get_user_config()
    api_key = config.get("api_key", "")
    masked = ("***" + api_key[-6:]) if len(api_key) > 6 else ("•" * len(api_key))
    return {**config, "api_key": masked, "api_key_set": bool(api_key)}


@router.post("/api/settings")
async def update_settings(request: SettingsUpdateRequest) -> dict[str, object]:
    from routers._deps import get_session, make_llm_client

    session = get_session()
    updates = request.model_dump(exclude_none=True)
    save_user_config(updates)
    if any(key in updates for key in ("api_key", "model", "temperature", "top_p", "top_k", "max_tokens")):
        await session.replace_llm(make_llm_client())
    return {
        "status": "ok",
        "llm_connected": session.llm is not None,
        "model": get_user_config().get("model", ""),
    }


@router.get("/api/models")
async def list_models(q: str = "", provider: str = "") -> dict[str, object]:
    """Fetch OpenRouter models only when a user deliberately configures it."""

    config = get_user_config()
    try:
        models = await LLMClient.fetch_models(config.get("api_key", ""))
    except Exception as error:
        # Provider bodies can contain account details or reflected request
        # data.  Never make arbitrary upstream exception text part of the
        # public API response.
        raise HTTPException(
            status_code=502,
            detail="Could not fetch OpenRouter models.",
        ) from error
    if q:
        query = q.lower()
        models = [model for model in models if query in model["id"].lower() or query in model["name"].lower()]
    if provider:
        models = [model for model in models if model["provider"].lower() == provider.lower()]
    return {"models": models[:150]}


@router.get("/api/characters")
async def list_characters() -> dict[str, object]:
    """Public CCv3 summaries only; no case-assigned role or private truth."""

    characters = []
    for character_id in list_content_ids(CHARACTER_CARDS_DIR):
        card = load_character_card(character_id)
        extension = card.data.extensions.murder_mystery
        characters.append(
            {
                "id": character_id,
                "name": card.data.name,
                "description": card.data.description,
                "tags": list(card.data.tags),
                "public_biography": extension.public_biography,
                "appearance": extension.appearance,
                "speaking_style": extension.speaking_style,
            }
        )
    return {"characters": characters}
