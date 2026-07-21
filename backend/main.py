"""FastAPI application for the local-first deterministic mystery MVP."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import routers._deps as _deps
from config.settings import DEFAULT_HOST, DEFAULT_PORT, SAVE_ROOT, STATIC_DIR
from config.user_settings import get_user_config, load_user_config
from game.service import GameService
from llm.client import LLMClient
from routers import game as game_router
from routers import cards as cards_router
from routers import settings as settings_router
from routers import ws as ws_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _make_llm_client() -> LLMClient | None:
    """Build the configured OpenRouter client used by generated play."""

    config = get_user_config()
    if not config.get("api_key"):
        return None
    return LLMClient(
        api_key=config["api_key"],
        model=config.get("model", ""),
        temperature=config.get("temperature", 0.8),
        top_p=config.get("top_p", 0.95),
        top_k=config.get("top_k", 40),
        max_tokens=config.get("max_tokens", 1024),
    )


_session = GameService(SAVE_ROOT)
_ws_connections: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_user_config()
    _session.llm = _make_llm_client()
    _deps.init(session=_session, ws_pool=_ws_connections, llm_factory=_make_llm_client)
    logger.info("AI Murder Mystery v2 deterministic backend started")
    yield
    logger.info("Backend shut down")


app = FastAPI(
    title="AI Murder Mystery v2",
    description="Local-first, deterministic turn-based murder mystery",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

app.include_router(game_router.router)
app.include_router(cards_router.router)
app.include_router(ws_router.router)
app.include_router(settings_router.router)


@app.get("/og.png", include_in_schema=False)
async def social_preview():
    """Serve the generated social preview beside the single-page app."""

    image = STATIC_DIR / "og.png"
    if image.exists():
        return FileResponse(image, media_type="image/png")
    raise HTTPException(status_code=404, detail="Social preview is not built.")


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Serve the Vite SPA for non-API routes in production builds."""

    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"error": "Frontend not built. Run npm run build in frontend/."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=DEFAULT_HOST, port=DEFAULT_PORT, reload=True)
