"""HTTP transport for the deterministic, local-first game session."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from game.actions import parse_player_intent
from game.persistence import SaveValidationError
from game.service import DEFAULT_CASE_ID, DEFAULT_LOCATION_ID


router = APIRouter(prefix="/api/game")


class StartGameRequest(BaseModel):
    """The vertical slice is fixed content, but IDs remain explicit for saves."""

    case_id: str = DEFAULT_CASE_ID
    location_id: str = DEFAULT_LOCATION_ID


class SaveRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=120)


def _service():
    from routers._deps import get_session

    session = get_session()
    if session is None:
        raise HTTPException(status_code=503, detail="Game service is not initialised.")
    return session


def _not_found_or_bad_request(error: Exception) -> HTTPException:
    if isinstance(error, FileNotFoundError):
        return HTTPException(status_code=404, detail="Requested game content or save was not found.")
    return HTTPException(status_code=400, detail=str(error))


@router.get("/catalog")
async def catalog() -> dict[str, object]:
    """Fixed map and public CCv3 character summaries; no case truth."""

    return _service().catalog()


@router.get("/bootstrap")
async def bootstrap() -> dict[str, object]:
    """A single public payload for a client reconnect or initial render."""

    return _service().bootstrap()


@router.post("/new")
async def new_game(request: StartGameRequest) -> dict[str, object]:
    """Start Ashwick deterministically; an API key is never required."""

    try:
        game = _service().start(case_id=request.case_id, location_id=request.location_id)
    except (FileNotFoundError, ValueError) as error:
        raise _not_found_or_bad_request(error) from error
    return {"status": "ok", "game": game.model_dump(mode="json"), "catalog": _service().catalog()}


@router.get("/state")
async def get_game_state() -> dict[str, object]:
    try:
        return _service().state().model_dump(mode="json")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/action")
async def action(payload: dict[str, Any]) -> dict[str, object]:
    """Apply one discriminated player intent through the authoritative engine."""

    try:
        intent = parse_player_intent(payload)
    except ValidationError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=error.errors()) from error
    try:
        result = _service().apply(intent.model_dump(mode="python"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return result.model_dump(mode="json")


@router.get("/saves/v1")
async def list_saves() -> dict[str, object]:
    return {"schema_version": 1, "saves": _service().list_saves()}


@router.post("/saves/v1")
async def save_game(request: SaveRequest) -> dict[str, object]:
    try:
        filename = _service().save(request.filename)
    except (SaveValidationError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"schema_version": 1, "status": "saved", "filename": filename}


@router.post("/saves/v1/{filename}/load")
async def load_game(filename: str) -> dict[str, object]:
    try:
        game = _service().load(filename)
    except (SaveValidationError, ValueError, FileNotFoundError) as error:
        raise _not_found_or_bad_request(error) from error
    return {"schema_version": 1, "status": "loaded", "game": game.model_dump(mode="json")}


@router.get("/debrief")
async def debrief() -> dict[str, object]:
    """Reveal canonical truth only once a result or timeout has ended play."""

    try:
        return _service().debrief()
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
