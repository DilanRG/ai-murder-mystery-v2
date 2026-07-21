"""Launch one opaque, restricted Phase A crossed play session on localhost."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
from typing import Sequence

import uvicorn

from config.user_settings import get_user_config, load_user_config
from experiments.deepseek_v4_blind import BlindTranscriptRecorder, build_blind_app
from experiments.deepseek_v4_crossed import (
    build_crossed_cells,
    load_generation_results,
    prepare_crossed_session,
    select_first_admitted_cases,
    write_crossed_plan,
)
from experiments.deepseek_v4_runner import (
    PRIVATE_ARTIFACT_ROOT,
    load_manifest,
    load_private_preflights,
    resolve_clean_git_sha,
)
from launcher import _valid_port, find_free_port


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch one restricted blind play session")
    parser.add_argument("--cell", required=True, choices=("A", "B", "C", "D"))
    parser.add_argument("--port", type=_valid_port)
    return parser.parse_args(argv)


def _append_private_controller_record(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _append_runtime_diagnostics(
    path: Path,
    *,
    session_id: str,
    records: list[dict[str, object]],
) -> None:
    for record in records:
        _append_private_controller_record(
            path,
            {
                "schema_version": 1,
                "session_id": session_id,
                **record,
            },
        )


async def _prepare(cell_id: str, *, phase: str = "phase_a"):
    manifest = load_manifest()
    git_sha = resolve_clean_git_sha()
    preflights = load_private_preflights(PRIVATE_ARTIFACT_ROOT / "verified_preflights.json")
    generation_results = load_generation_results(
        PRIVATE_ARTIFACT_ROOT / "generation_results.json"
    )
    selected = select_first_admitted_cases(
        manifest=manifest,
        generation_results=generation_results,
        git_sha=git_sha,
    )
    cells = build_crossed_cells(selected)
    write_crossed_plan(
        PRIVATE_ARTIFACT_ROOT / "crossed_plan.json",
        git_sha=git_sha,
        cells=cells,
    )
    cell = next(item for item in cells if item.cell_id == cell_id)
    load_user_config()
    api_key = str(get_user_config().get("api_key", ""))
    prepared = await prepare_crossed_session(
        manifest=manifest,
        preflight_evidence=preflights,
        git_sha=git_sha,
        api_key=api_key,
        cell=cell,
        explicitly_enabled=True,
        phase=phase,
    )
    return prepared, git_sha


def main(argv: Sequence[str] | None = None) -> int:
    if os.environ.get("AI_MYSTERY_ENABLE_PHASE_A") != "1":
        raise RuntimeError("Set the explicit Phase A enable flag to launch measured play.")
    options = parse_args(argv)
    prepared, git_sha = asyncio.run(_prepare(options.cell))
    session_root = PRIVATE_ARTIFACT_ROOT / "blind_sessions"
    session_id = secrets.token_hex(16)
    recorder = BlindTranscriptRecorder(
        session_root / session_id / "transcript.jsonl",
        session_id=session_id,
    )
    _append_private_controller_record(
        session_root / "controller_index.jsonl",
        {
            "schema_version": 1,
            "session_id": recorder.session_id,
            "git_sha": git_sha,
            "cell_id": prepared.cell.cell_id,
            "generation_model_key": prepared.cell.generated_case.generation_model_key,
            "npc_model_key": prepared.cell.npc_model_key,
            "pair_id": prepared.cell.generated_case.pair_id,
            "case_fingerprint": prepared.cell.generated_case.case_fingerprint,
        },
    )
    app = build_blind_app(
        service=prepared.service,
        recorder=recorder,
        provider_stop=lambda: prepared.measured_client.abort_code,
        diagnostic_sink=lambda records: _append_runtime_diagnostics(
            session_root / recorder.session_id / "runtime_diagnostics.jsonl",
            session_id=recorder.session_id,
            records=records,
        ),
    )
    port = options.port or find_free_port(8801, 8850)
    print(
        json.dumps(
            {
                "session_id": recorder.session_id,
                "url": f"http://127.0.0.1:{port}",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        if not recorder.sealed:
            recorder.seal(reason="server_shutdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
