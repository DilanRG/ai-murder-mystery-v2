"""Frozen Phase B manifest and append-only defect evidence."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import Field

from experiments.deepseek_v4_runner import ExperimentSafetyError
from game.models import StrictModel


MANIFEST_PATH = Path(__file__).with_name("deepseek_v4_adversarial_manifest.json")


class AdversarialDefect(StrictModel):
    schema_version: Literal[1] = 1
    defect_id: str = Field(pattern=r"^ADV-[A-Z0-9-]{1,80}$")
    session_id: Literal["ADV-PRO", "ADV-FLASH"]
    npc_model_key: Literal["pro", "flash"]
    severity: Literal["critical", "major", "minor"]
    status: Literal["confirmed", "fixed", "rejected", "deferred"]
    reproduction: str = Field(min_length=1, max_length=4_000)
    expected_behavior: str = Field(min_length=1, max_length=2_000)
    actual_behavior: str = Field(min_length=1, max_length=2_000)
    authoritative_state_impact: str = Field(min_length=1, max_length=2_000)
    cost_impact: str = Field(min_length=1, max_length=2_000)
    hidden_state_impact: str = Field(min_length=1, max_length=2_000)
    fix: str = Field(default="", max_length=4_000)
    regression_evidence: str = Field(default="", max_length=4_000)


def load_adversarial_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentSafetyError("Adversarial manifest could not be read.") from error
    if manifest.get("schema_version") != 1:
        raise ExperimentSafetyError("Only adversarial manifest revision 1 is accepted.")
    if manifest.get("entry_gate") != "phase_a_passed_and_budget_available":
        raise ExperimentSafetyError("Phase B must remain gated on Phase A and budget.")
    sessions = manifest.get("sessions")
    if not isinstance(sessions, list) or [
        (item.get("session_id"), item.get("npc_model_key"))
        for item in sessions
        if isinstance(item, Mapping)
    ] != [("ADV-PRO", "pro"), ("ADV-FLASH", "flash")]:
        raise ExperimentSafetyError("Phase B requires one frozen Pro and one Flash session.")
    required = manifest.get("required_invariants")
    attacks = manifest.get("attack_groups")
    if not isinstance(required, list) or len(required) < 8:
        raise ExperimentSafetyError("Adversarial invariants are incomplete.")
    if not isinstance(attacks, list) or len(attacks) < 12:
        raise ExperimentSafetyError("Adversarial attack groups are incomplete.")
    surface = manifest.get("surface")
    if not isinstance(surface, Mapping) or not surface.get("validated_save_load"):
        raise ExperimentSafetyError("Phase B must exercise player-visible save/load.")
    if any(surface.get(name) for name in ("new_game", "demo", "settings", "models", "card_editor", "premature_debrief", "openapi")):
        raise ExperimentSafetyError("Phase B may not expose developer or hidden-state routes.")
    return manifest


def append_defect(path: Path, defect: AdversarialDefect) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = defect.model_dump(mode="json") | {
        "recorded_at": datetime.now(UTC).isoformat()
    }
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
