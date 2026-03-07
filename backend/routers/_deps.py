"""
routers/_deps.py — Shared dependency accessors for all routers.

Routes cannot import _session directly from main.py (circular import).
Instead they call get_session() / get_ws_connections() / broadcast() here.
These are module-level singletons initialised once by main.py at startup.
"""
from __future__ import annotations
from typing import Any, Callable, Awaitable

_session = None
_ws_connections: set = set()
_llm_factory: Callable | None = None


def init(session, ws_pool: set, llm_factory: Callable) -> None:
    """Called once from main.py lifespan to wire up the shared state."""
    global _session, _ws_connections, _llm_factory
    _session = session
    _ws_connections = ws_pool
    _llm_factory = llm_factory


def get_session():
    return _session


def get_ws_connections() -> set:
    return _ws_connections


def make_llm_client():
    return _llm_factory() if _llm_factory else None


async def broadcast(data: dict[str, Any]) -> None:
    """Broadcast JSON to all live WebSocket clients."""
    from fastapi import WebSocket
    dead: set = set()
    for ws in _ws_connections:
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    _ws_connections.difference_update(dead)
