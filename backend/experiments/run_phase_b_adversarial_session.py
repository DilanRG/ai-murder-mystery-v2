"""Launch one gated adversarial player session with Pro or Flash NPCs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
from typing import Sequence

import uvicorn

from experiments.deepseek_v4_blind import BlindTranscriptRecorder, build_blind_app
from experiments.deepseek_v4_runner import PRIVATE_ARTIFACT_ROOT, ExperimentSafetyError
from experiments.run_phase_a_blind_session import (
    _append_private_controller_record,
    _append_runtime_diagnostics,
    _prepare,
)
from launcher import _valid_port, find_free_port


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch a restricted Phase B session")
    parser.add_argument("--npc-model", required=True, choices=("pro", "flash"))
    parser.add_argument("--port", type=_valid_port)
    return parser.parse_args(argv)


def _verify_phase_a_gate(path: Path, *, git_sha: str) -> dict[str, object]:
    try:
        gate = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentSafetyError("Phase B requires a sealed Phase A gate record.") from error
    if (
        not isinstance(gate, dict)
        or gate.get("passed") is not True
        or gate.get("git_sha") != git_sha
        or gate.get("sealed_session_count") != 4
        or gate.get("supported_accusations", 0) < 2
        or gate.get("supported_pro_npc_accusations", 0) < 1
        or gate.get("supported_flash_npc_accusations", 0) < 1
        or gate.get("major_mechanical_blockers", 1) != 0
        or gate.get("hidden_state_leaks", 1) != 0
    ):
        raise ExperimentSafetyError("Phase A evidence does not satisfy the Phase B entry gate.")
    return gate


def main(argv: Sequence[str] | None = None) -> int:
    if os.environ.get("AI_MYSTERY_ENABLE_PHASE_B") != "1":
        raise RuntimeError("Set the explicit Phase B enable flag to launch adversarial play.")
    options = parse_args(argv)
    # A and D give the requested NPC model its corresponding pristine selected
    # case. Each adversarial player is fresh and has no earlier transcript.
    cell_id = "A" if options.npc_model == "pro" else "D"
    prepared, git_sha = asyncio.run(_prepare(cell_id, phase="phase_b"))
    _verify_phase_a_gate(
        PRIVATE_ARTIFACT_ROOT / "phase_a_gate.json",
        git_sha=git_sha,
    )
    session_root = PRIVATE_ARTIFACT_ROOT / "adversarial_sessions"
    session_id = secrets.token_hex(16)
    recorder = BlindTranscriptRecorder(
        session_root / session_id / "transcript.jsonl",
        session_id=session_id,
    )
    _append_private_controller_record(
        session_root / "controller_index.jsonl",
        {
            "schema_version": 1,
            "session_id": session_id,
            "git_sha": git_sha,
            "session_label": "ADV-PRO" if options.npc_model == "pro" else "ADV-FLASH",
            "cell_id": prepared.cell.cell_id,
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
            session_root / session_id / "runtime_diagnostics.jsonl",
            session_id=session_id,
            records=records,
        ),
        allow_save_load=True,
    )
    port = options.port or find_free_port(8851, 8900)
    print(
        json.dumps(
            {"session_id": session_id, "url": f"http://127.0.0.1:{port}"},
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
