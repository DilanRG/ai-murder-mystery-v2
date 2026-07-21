"""Offline Phase B manifest and defect-ledger contracts."""

from __future__ import annotations

import json

import pytest

from experiments.deepseek_v4_adversarial import (
    AdversarialDefect,
    append_defect,
    load_adversarial_manifest,
)
from experiments.deepseek_v4_runner import ExperimentSafetyError
from experiments.run_phase_b_adversarial_session import _verify_phase_a_gate


def test_adversarial_manifest_has_two_models_real_surfaces_and_ordinary_regression() -> None:
    manifest = load_adversarial_manifest()

    assert [(item["session_id"], item["npc_model_key"]) for item in manifest["sessions"]] == [
        ("ADV-PRO", "pro"),
        ("ADV-FLASH", "flash"),
    ]
    assert manifest["surface"]["validated_save_load"] is True
    assert manifest["surface"]["premature_debrief"] is False
    assert "ordinary_valid_action_after_adversarial_rejections" in manifest["attack_groups"]
    assert "ordinary_valid_action_still_succeeds" in manifest["required_invariants"]


def test_defect_ledger_is_append_only_structured_and_contains_impact_fields(tmp_path) -> None:
    path = tmp_path / "defects.jsonl"
    defect = AdversarialDefect(
        defect_id="ADV-DOUBLE-SUBMIT",
        session_id="ADV-PRO",
        npc_model_key="pro",
        severity="major",
        status="confirmed",
        reproduction="Submit the same accepted action concurrently twice.",
        expected_behavior="At most one authoritative commit occurs.",
        actual_behavior="Two commits were observed in the hypothetical fixture.",
        authoritative_state_impact="The turn would advance twice.",
        cost_impact="Could duplicate seven NPC request groups.",
        hidden_state_impact="None observed.",
    )

    append_defect(path, defect)
    append_defect(path, defect.model_copy(update={"status": "fixed"}))

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["status"] for record in records] == ["confirmed", "fixed"]
    assert all(record["recorded_at"].endswith("+00:00") for record in records)
    assert all("authoritative_state_impact" in record for record in records)
    assert all("cost_impact" in record for record in records)
    assert all("hidden_state_impact" in record for record in records)


def test_phase_b_gate_requires_all_four_seals_and_both_npc_models(tmp_path) -> None:
    path = tmp_path / "phase_a_gate.json"
    gate = {
        "passed": True,
        "git_sha": "f" * 40,
        "sealed_session_count": 4,
        "supported_accusations": 2,
        "supported_pro_npc_accusations": 1,
        "supported_flash_npc_accusations": 1,
        "major_mechanical_blockers": 0,
        "hidden_state_leaks": 0,
    }
    path.write_text(json.dumps(gate), encoding="utf-8")
    assert _verify_phase_a_gate(path, git_sha="f" * 40) == gate

    gate["supported_flash_npc_accusations"] = 0
    path.write_text(json.dumps(gate), encoding="utf-8")
    with pytest.raises(ExperimentSafetyError, match="entry gate"):
        _verify_phase_a_gate(path, git_sha="f" * 40)
