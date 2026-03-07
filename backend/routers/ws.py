"""
routers/ws.py — WebSocket event stream endpoint.
"""
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/events")
async def websocket_events(ws: WebSocket):
    """Real-time event stream for the frontend."""
    from routers._deps import get_ws_connections
    ws_connections = get_ws_connections()

    await ws.accept()
    ws_connections.add(ws)
    logger.info("WebSocket client connected. Total: %d", len(ws_connections))
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        ws_connections.discard(ws)
        logger.info("WebSocket client disconnected. Total: %d", len(ws_connections))
