"""Settings, optional OpenRouter discovery, and public character card data."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.user_settings import get_user_config, save_user_config
from game.content import CHARACTER_CARDS_DIR, list_content_ids, load_character_card
from llm.client import LLMClient


router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    context_tokens: int | None = None
    autonomy: str | None = None
    timer_mode: str | None = None
    timer_minutes: int | None = None
    difficulty: str | None = None


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
        session.llm = make_llm_client()
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
        raise HTTPException(status_code=502, detail=f"Could not fetch models: {error}") from error
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
