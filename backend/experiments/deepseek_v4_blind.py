"""Restricted player-only Phase A surface with append-only transcript sealing."""

from __future__ import annotations

from datetime import UTC, datetime
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
from typing import Any, Callable, Mapping

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from game.actions import parse_player_intent
from game.persistence import SAVE_SCHEMA_VERSION, SaveValidationError
from game.service import GameService


FORBIDDEN_RESPONSE_KEYS = frozenset(
    {
        "api_key",
        "canonical_truth",
        "case_document",
        "culprit_id",
        "murderer_id",
        "model",
        "npc_private_state",
        "pair_id",
        "private_overlay",
        "provider",
        "run_id",
        "solution_routes",
    }
)


class _BlindSaveRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=120)


def _assert_public_response(value: object) -> None:
    if isinstance(value, Mapping):
        forbidden = {str(key).casefold() for key in value}.intersection(
            FORBIDDEN_RESPONSE_KEYS
        )
        if forbidden:
            raise RuntimeError("Blind response contains a forbidden hidden-state field.")
        for item in value.values():
            _assert_public_response(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_public_response(item)


class BlindTranscriptRecorder:
    """Append public request/response exchanges, then seal them by digest."""

    def __init__(self, transcript_path: Path, *, session_id: str | None = None) -> None:
        self.path = transcript_path
        self.session_id = session_id or secrets.token_hex(16)
        self.seal_path = self.path.with_suffix(self.path.suffix + ".seal.json")
        self._sequence = 0
        self._sealed = False
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() or self.seal_path.exists():
            raise ValueError("Blind transcript paths must be new for each session.")

    @property
    def sealed(self) -> bool:
        return self._sealed

    def record(
        self,
        *,
        method: str,
        path: str,
        request: object,
        status_code: int,
        response: object,
    ) -> None:
        _assert_public_response(response)
        with self._lock:
            if self._sealed:
                raise RuntimeError("Blind transcript is already sealed.")
            self._sequence += 1
            record = {
                "schema_version": 1,
                "session_id": self.session_id,
                "sequence": self._sequence,
                "recorded_at": datetime.now(UTC).isoformat(),
                "method": method,
                "path": path,
                "request": request,
                "status_code": status_code,
                "response": response,
            }
            encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())

    def seal(self, *, reason: str) -> dict[str, object]:
        if not reason or len(reason) > 120:
            raise ValueError("A short transcript seal reason is required.")
        with self._lock:
            if self._sealed:
                return json.loads(self.seal_path.read_text(encoding="utf-8"))
            payload = self.path.read_bytes() if self.path.exists() else b""
            seal = {
                "schema_version": 1,
                "session_id": self.session_id,
                "record_count": self._sequence,
                "sealed_at": datetime.now(UTC).isoformat(),
                "reason": reason,
                "transcript_sha256": hashlib.sha256(payload).hexdigest(),
            }
            temporary = self.seal_path.with_suffix(self.seal_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(seal, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.seal_path)
            self._sealed = True
            return seal

    def verify_seal(self) -> bool:
        if not self.seal_path.is_file():
            return False
        try:
            seal = json.loads(self.seal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        payload = self.path.read_bytes() if self.path.exists() else b""
        return (
            seal.get("session_id") == self.session_id
            and seal.get("record_count") == self._sequence
            and seal.get("transcript_sha256") == hashlib.sha256(payload).hexdigest()
        )


def build_blind_app(
    *,
    service: GameService,
    recorder: BlindTranscriptRecorder,
    provider_stop: Callable[[], str | None] | None = None,
    diagnostic_sink: Callable[[list[dict[str, object]]], None] | None = None,
    allow_save_load: bool = False,
) -> FastAPI:
    """Expose only ordinary player projections; never mount normal admin routes."""

    app = FastAPI(
        title="Mystery Play Session",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    diagnostic_cursor = 0

    def ensure_open() -> None:
        if recorder.sealed:
            raise HTTPException(status_code=409, detail="This play session is sealed.")

    def record_get(path: str, response: object) -> object:
        recorder.record(
            method="GET",
            path=path,
            request=None,
            status_code=200,
            response=response,
        )
        return response

    @app.get("/api/health")
    async def health() -> object:
        ensure_open()
        return record_get("/api/health", {"status": "ready"})

    @app.get("/api/game/bootstrap")
    async def bootstrap() -> object:
        ensure_open()
        catalog = copy.deepcopy(service.catalog())
        generation = catalog.get("generation")
        if isinstance(generation, dict):
            generation.pop("provider", None)
        response = {
            "catalog": catalog,
            "game": service.state().model_dump(mode="json"),
            "recipe": None,
            "generation": None,
        }
        return record_get("/api/game/bootstrap", response)

    @app.get("/api/game/state")
    async def state_view() -> object:
        ensure_open()
        return record_get(
            "/api/game/state",
            service.state().model_dump(mode="json"),
        )

    @app.get("/api/game/saves/v2")
    async def saves() -> object:
        ensure_open()
        return record_get(
            "/api/game/saves/v2",
            {
                "schema_version": SAVE_SCHEMA_VERSION,
                "saves": service.list_saves() if allow_save_load else [],
            },
        )

    async def save_game(request: _BlindSaveRequest) -> object:
        ensure_open()
        request_document = request.model_dump(mode="json")
        try:
            filename = service.save(request.filename)
        except (SaveValidationError, ValueError) as error:
            response = {"detail": str(error)}
            recorder.record(
                method="POST",
                path="/api/game/saves/v2",
                request=request_document,
                status_code=400,
                response=response,
            )
            raise HTTPException(status_code=400, detail=str(error)) from error
        response = {
            "schema_version": SAVE_SCHEMA_VERSION,
            "status": "saved",
            "filename": filename,
        }
        recorder.record(
            method="POST",
            path="/api/game/saves/v2",
            request=request_document,
            status_code=200,
            response=response,
        )
        return response

    async def load_game(filename: str) -> object:
        ensure_open()
        try:
            game = await service.load_async(filename)
        except (SaveValidationError, ValueError, FileNotFoundError) as error:
            status_code = 404 if isinstance(error, FileNotFoundError) else 400
            response = {"detail": str(error)}
            recorder.record(
                method="POST",
                path="/api/game/saves/v2/{filename}/load",
                request={"filename": filename},
                status_code=status_code,
                response=response,
            )
            raise HTTPException(status_code=status_code, detail=str(error)) from error
        response = {
            "schema_version": SAVE_SCHEMA_VERSION,
            "status": "loaded",
            "game": game.model_dump(mode="json"),
            "recipe": None,
        }
        recorder.record(
            method="POST",
            path="/api/game/saves/v2/{filename}/load",
            request={"filename": filename},
            status_code=200,
            response=response,
        )
        return response

    @app.post("/api/game/action")
    async def action(payload: dict[str, Any]) -> object:
        nonlocal diagnostic_cursor
        ensure_open()
        try:
            intent = parse_player_intent(payload)
        except ValidationError as error:
            detail = error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
            recorder.record(
                method="POST",
                path="/api/game/action",
                request=payload,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                response={"detail": detail},
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=detail,
            ) from error
        try:
            response = await service.action(intent)
        except ValueError as error:
            safe = {"detail": str(error)}
            recorder.record(
                method="POST",
                path="/api/game/action",
                request=payload,
                status_code=400,
                response=safe,
            )
            raise HTTPException(status_code=400, detail=str(error)) from error
        recorder.record(
            method="POST",
            path="/api/game/action",
            request=payload,
            status_code=200,
            response=response,
        )
        diagnostics = service.runtime_diagnostics()
        if diagnostic_sink is not None and len(diagnostics) > diagnostic_cursor:
            diagnostic_sink(diagnostics[diagnostic_cursor:])
        diagnostic_cursor = len(diagnostics)
        result = response.get("game", {}).get("result")
        if result is not None:
            recorder.seal(reason="normal_game_end")
        elif provider_stop is not None and provider_stop() is not None:
            recorder.seal(reason="runtime_provider_stop")
        return response

    if allow_save_load:
        app.add_api_route(
            "/api/game/saves/v2",
            save_game,
            methods=["POST"],
        )
        app.add_api_route(
            "/api/game/saves/v2/{filename}/load",
            load_game,
            methods=["POST"],
        )

    return app
