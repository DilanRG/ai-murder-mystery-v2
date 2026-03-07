"""
AI Murder Mystery v2 — FastAPI Backend
Main entry point — wires up routers, middleware, static files, and lifecycle.
Business logic lives in routers/ and domain modules.
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi import WebSocket

from config.settings import DEFAULT_HOST, DEFAULT_PORT, STATIC_DIR
from config.user_settings import load_user_config, get_user_config
from llm.client import LLMClient
from world.state import WorldState, GamePhase
from world.event_bus import EventBus
from world.clock import GameClock
from agents.manager import AgentManager

from routers import game as game_router
from routers import ws as ws_router
from routers import settings as settings_router
import routers._deps as _deps

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ── Runtime Game Session ───────────────────────────────────────────────────────

class GameSession:
    """Holds all per-game runtime state. Replaced on each new game."""
    def __init__(self) -> None:
        self.scenario = None
        self.world: WorldState | None = None
        self.event_bus: EventBus = EventBus()
        self.llm: LLMClient | None = None
        self.player_name: str = ""
        self.difficulty: str = "normal"
        self.briefings: dict = {}
        self.agent_manager: AgentManager | None = None
        self.clock: GameClock = GameClock()
        self.agent_tasks: list[asyncio.Task] = []

    def is_active(self) -> bool:
        return self.world is not None and self.world.game_phase == GamePhase.PLAYING


# Module-level singletons — shared via _deps
_session: GameSession = GameSession()
_ws_connections: set[WebSocket] = set()


def _make_llm_client() -> LLMClient | None:
    """Construct an LLMClient from current user config, or None if no API key."""
    cfg = get_user_config()
    if not cfg.get("api_key"):
        return None
    return LLMClient(
        api_key=cfg["api_key"],
        model=cfg.get("model", ""),
        temperature=cfg.get("temperature", 0.8),
        top_p=cfg.get("top_p", 0.95),
        top_k=cfg.get("top_k", 40),
        max_tokens=cfg.get("max_tokens", 1024),
    )


# ── Application Lifecycle ──────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load config, init LLM client, wire shared deps. Shutdown: cancel agents."""
    logger.info("AI Murder Mystery v2 -- Starting...")
    load_user_config()
    _session.llm = _make_llm_client()
    if _session.llm:
        logger.info("LLM client ready -- model: %s", get_user_config().get("model"))
    else:
        logger.warning("No API key configured. Set one via Settings before starting a game.")

    # Wire the shared dependency layer
    _deps.init(
        session=_session,
        ws_pool=_ws_connections,
        llm_factory=_make_llm_client,
    )

    yield

    # Graceful shutdown
    for task in _session.agent_tasks:
        task.cancel()
    logger.info("Backend shut down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Murder Mystery v2",
    description="Continuous agent-based murder mystery game",
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

# Static assets (Vite build — production only)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

# Register routers
app.include_router(game_router.router)
app.include_router(ws_router.router)
app.include_router(settings_router.router)


# ── Frontend SPA Fallback ─────────────────────────────────────────────────────

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Serve the Vite-built frontend for any unmatched route (SPA fallback)."""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"error": "Frontend not built. Run `npm run build` in frontend/."}


# ── Dev entrypoint ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=DEFAULT_HOST, port=DEFAULT_PORT, reload=True)
