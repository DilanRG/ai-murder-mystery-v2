"""HTTP transport for the deterministic, local-first game session."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from game.actions import InterviewExchangeIntent, parse_player_intent
from game.case_generation import GeneratedScenarioError
from game.persistence import SAVE_SCHEMA_VERSION, SaveValidationError
from game.recipes import MAX_RECIPE_SEED
from game.service import DEFAULT_CASE_ID, DEFAULT_LOCATION_ID


router = APIRouter(prefix="/api/game")


class DemoStartRequest(BaseModel):
    """Choose either explicit authored content or one seeded case recipe."""

    model_config = ConfigDict(extra="forbid")

    case_id: str | None = Field(default=None, min_length=1, max_length=64)
    location_id: str | None = Field(default=None, min_length=1, max_length=64)
    recipe_id: str | None = Field(default=None, min_length=1, max_length=64)
    seed: StrictInt | None = Field(default=None, ge=0, le=MAX_RECIPE_SEED)
    character_ids: tuple[str, ...] | None = Field(default=None, min_length=8, max_length=8)

    @model_validator(mode="after")
    def validate_mode(self) -> "DemoStartRequest":
        if self.recipe_id is not None:
            if self.seed is None:
                raise ValueError("a recipe start requires a seed")
            if self.case_id is not None or self.location_id is not None:
                raise ValueError("recipe and fixed-content fields cannot be combined")
        elif self.seed is not None:
            raise ValueError("a seed requires a recipe_id")
        elif self.character_ids is not None:
            raise ValueError("manual character selection requires a recipe_id")
        if self.character_ids is not None and len(set(self.character_ids)) != 8:
            raise ValueError("manual character selection requires eight unique IDs")
        return self


class GeneratedStartRequest(BaseModel):
    """Select a location and any eight cards for provider-backed generation."""

    model_config = ConfigDict(extra="forbid")

    seed: StrictInt = Field(ge=0, le=MAX_RECIPE_SEED)
    location_id: str = Field(default=DEFAULT_LOCATION_ID, min_length=1, max_length=64)
    character_ids: tuple[str, ...] | None = Field(
        default=None,
        min_length=8,
        max_length=8,
    )
    difficulty: Literal["easy", "normal", "hard"] = "normal"

    @model_validator(mode="after")
    def validate_characters(self) -> "GeneratedStartRequest":
        if self.character_ids is not None and len(set(self.character_ids)) != 8:
            raise ValueError("manual character selection requires eight unique IDs")
        return self


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
async def new_game(request: GeneratedStartRequest) -> dict[str, object]:
    """Generate and validate canonical truth from the chosen cards and location."""

    try:
        game = await _service().start_generated_async(
            seed=request.seed,
            location_id=request.location_id,
            character_ids=request.character_ids,
            difficulty=request.difficulty,
        )
    except GeneratedScenarioError as error:
        status_code = {
            "provider_not_configured": 428,
            "provider_rate_limited": 429,
            "provider_unavailable": 503,
            "provider_timeout": 504,
        }.get(error.code, 502)
        message = {
            "provider_not_configured": "Add an OpenRouter API key in Settings to generate a new story.",
            "provider_auth_failed": "OpenRouter rejected the stored API key. Update it in Settings.",
            "provider_rate_limited": "OpenRouter is rate-limiting requests. Wait briefly and try again.",
            "provider_timeout": "OpenRouter timed out while generating the story. Try again.",
            "provider_unavailable": "OpenRouter is currently unavailable. Try again later.",
        }.get(
            error.code,
            "The generated story did not pass validation. Try again.",
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code, "message": message},
        ) from error
    except (FileNotFoundError, ValueError) as error:
        raise _not_found_or_bad_request(error) from error
    return {
        "status": "ok",
        "game": game.model_dump(mode="json"),
        "catalog": _service().catalog(),
        "generation": _service().generation_metadata(),
    }


@router.post("/demo")
async def demo_game(request: DemoStartRequest) -> dict[str, object]:
    """Start an explicitly offline authored fixture without calling OpenRouter."""

    try:
        if request.recipe_id is not None:
            assert request.seed is not None
            game = await _service().start_recipe_async(
                recipe_id=request.recipe_id,
                seed=request.seed,
                character_ids=request.character_ids,
            )
        else:
            game = await _service().start_async(
                case_id=request.case_id or DEFAULT_CASE_ID,
                location_id=request.location_id or DEFAULT_LOCATION_ID,
            )
    except (FileNotFoundError, ValueError) as error:
        raise _not_found_or_bad_request(error) from error
    return {
        "status": "ok",
        "game": game.model_dump(mode="json"),
        "catalog": _service().catalog(),
        "recipe": _service().recipe_metadata(),
        "generation": None,
    }


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
        # Pydantic's validation context can contain the original ValueError,
        # which Starlette's JSON response encoder cannot serialize. Inputs are
        # excluded as well so a rejected megabyte-scale payload is not echoed
        # back to the client.
        detail = error.errors(include_url=False, include_context=False, include_input=False)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail) from error
    if isinstance(intent, InterviewExchangeIntent) and not (1 <= len(intent.message.strip()) <= 1_200):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Interview questions must contain 1 to 1200 non-whitespace characters.",
        )
    try:
        result = await _service().action(intent)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return result


@router.get("/saves/v2")
@router.get("/saves/v1", include_in_schema=False)
async def list_saves() -> dict[str, object]:
    return {"schema_version": SAVE_SCHEMA_VERSION, "saves": _service().list_saves()}


@router.post("/saves/v2")
@router.post("/saves/v1", include_in_schema=False)
async def save_game(request: SaveRequest) -> dict[str, object]:
    try:
        filename = _service().save(request.filename)
    except (SaveValidationError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"schema_version": SAVE_SCHEMA_VERSION, "status": "saved", "filename": filename}


@router.post("/saves/v2/{filename}/load")
@router.post("/saves/v1/{filename}/load", include_in_schema=False)
async def load_game(filename: str) -> dict[str, object]:
    try:
        game = await _service().load_async(filename)
    except (SaveValidationError, ValueError, FileNotFoundError) as error:
        raise _not_found_or_bad_request(error) from error
    return {
        "schema_version": SAVE_SCHEMA_VERSION,
        "status": "loaded",
        "game": game.model_dump(mode="json"),
        "recipe": _service().recipe_metadata(),
    }


@router.get("/debrief")
async def debrief() -> dict[str, object]:
    """Reveal canonical truth only once a result or timeout has ended play."""

    try:
        return _service().debrief()
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
