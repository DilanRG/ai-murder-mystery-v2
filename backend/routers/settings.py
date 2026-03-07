"""
routers/settings.py — Settings, health, model list, and character pool endpoints.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

from config.user_settings import get_user_config, save_user_config
from llm.client import LLMClient
from story.characters import load_all_characters

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    context_tokens: int | None = None
    autonomy: str | None = None       # "low" | "high"
    timer_mode: str | None = None     # "none" | "realtime" | "event"
    timer_minutes: int | None = None
    difficulty: str | None = None


@router.get("/api/health")
async def health(session=None):
    """Health check — used by frontend to detect backend connection."""
    # session injected via dependency in main.py
    from routers._deps import get_session
    _session = get_session()
    cfg = get_user_config()
    return {
        "status": "ok",
        "llm_connected": bool(cfg.get("api_key")),
        "model": cfg.get("model", ""),
        "game_active": _session.is_active(),
    }


@router.get("/api/settings")
async def get_settings():
    cfg = get_user_config()
    api_key = cfg.get("api_key", "")
    masked = ("***" + api_key[-6:]) if len(api_key) > 6 else ("•" * len(api_key))
    return {**cfg, "api_key": masked, "api_key_set": bool(api_key)}


@router.post("/api/settings")
async def update_settings(req: SettingsUpdateRequest):
    from routers._deps import get_session, make_llm_client
    _session = get_session()
    updates = req.model_dump(exclude_none=True)
    save_user_config(updates)
    if any(k in updates for k in ("api_key", "model", "temperature", "top_p", "top_k", "max_tokens")):
        _session.llm = make_llm_client()
    return {
        "status": "ok",
        "llm_connected": _session.llm is not None,
        "model": get_user_config().get("model", ""),
    }


@router.get("/api/models")
async def list_models(q: str = "", provider: str = ""):
    """Fetch and search available models from OpenRouter (with pricing)."""
    cfg = get_user_config()
    try:
        models = await LLMClient.fetch_models(cfg.get("api_key", ""))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch models: {e}")
    if q:
        q_lower = q.lower()
        models = [m for m in models if q_lower in m["id"].lower() or q_lower in m["name"].lower()]
    if provider:
        models = [m for m in models if m["provider"].lower() == provider.lower()]
    return {"models": models[:150]}


@router.get("/api/characters")
async def list_characters():
    """Return the character pool summary for setup screen preview."""
    chars = load_all_characters()
    return {
        "characters": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description[:120] + "…",
                "tags": c.tags,
                "possible_roles": c.possible_roles,
                "moral_alignment": c.moral_alignment,
            }
            for c in chars
        ]
    }
