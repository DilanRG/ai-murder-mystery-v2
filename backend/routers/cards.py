"""Local JSON CCv3 validation, draft, and export endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import Field

from config.settings import CARD_DRAFT_ROOT
from game.card_library import (
    MAX_CARD_BYTES,
    CardImportResult,
    CardLibraryError,
    export_card_json,
    inspect_card_draft,
    safe_card_path,
    write_card_draft,
)
from game.content import load_character_card
from game.models import StrictModel


router = APIRouter(prefix="/api/cards")


class CardDraftRequest(StrictModel):
    raw_json: str = Field(min_length=1, max_length=MAX_CARD_BYTES)
    character_id: str | None = None
    replace: bool = False


def _public_result(result: CardImportResult) -> dict[str, object]:
    """Never serialize the validated card's prompt or lore back as preview."""

    return {
        "ok": result.ok,
        "preview": result.preview.model_dump(mode="json") if result.preview else None,
        "issues": [issue.model_dump(mode="json") for issue in result.issues],
    }


def _json_download(payload: bytes, character_id: str) -> Response:
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{character_id}.json"'},
    )


@router.post("/validate")
async def validate_card(request: CardDraftRequest) -> dict[str, object]:
    result = inspect_card_draft(request.raw_json, character_id=request.character_id)
    return _public_result(result)


@router.post("/drafts")
async def save_card_draft(request: CardDraftRequest) -> dict[str, object]:
    result = inspect_card_draft(request.raw_json, character_id=request.character_id)
    if not result.ok or result.card is None or result.preview is None:
        message = " ".join(issue.message for issue in result.issues) or "Card is invalid."
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=message,
        )
    try:
        path = write_card_draft(
            CARD_DRAFT_ROOT,
            result.preview.character_id,
            result.card,
            replace=request.replace,
        )
    except CardLibraryError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "status": "saved",
        "filename": path.name,
        "preview": result.preview.model_dump(mode="json"),
    }


@router.get("/drafts")
async def list_card_drafts() -> dict[str, object]:
    previews: list[dict[str, object]] = []
    root = Path(CARD_DRAFT_ROOT)
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            result = inspect_card_draft(raw, character_id=path.stem)
            if result.ok and result.preview:
                previews.append(result.preview.model_dump(mode="json"))
    return {"drafts": previews}


@router.get("/authored/{character_id}/export")
async def export_authored_card(character_id: str) -> Response:
    try:
        card = load_character_card(character_id)
        payload = export_card_json(card)
    except (ValueError, FileNotFoundError, CardLibraryError) as error:
        raise HTTPException(status_code=404, detail="Character card was not found.") from error
    return _json_download(payload, character_id)


@router.get("/drafts/{character_id}/export")
async def export_draft_card(character_id: str) -> Response:
    try:
        path = safe_card_path(CARD_DRAFT_ROOT, character_id)
        result = inspect_card_draft(path.read_bytes(), character_id=character_id)
        if not result.ok or result.card is None:
            raise CardLibraryError("stored draft is not a valid playable CCv3 card")
        payload = export_card_json(result.card)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Character-card draft was not found.") from error
    except CardLibraryError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _json_download(payload, character_id)
