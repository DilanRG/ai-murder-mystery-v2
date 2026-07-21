"""Offline checks for the frozen, no-traffic DeepSeek V4 experiment contract."""

from __future__ import annotations

import json

import pytest

from experiments.deepseek_v4_runner import (
    EXPECTED_MODELS,
    EXPECTED_ROUTING,
    ExperimentSafetyError,
    build_request,
    dry_run_summary,
    execute_with_verified_preflights,
    load_manifest,
    resolve_clean_git_sha,
    verify_preflights,
)


def _verified_preflights() -> dict[str, object]:
    return {
        key: {"model": slug, "upstream_provider": "deepseek", "is_byok": True, "fallback_used": False}
        for key, slug in EXPECTED_MODELS.items()
    }


def test_manifest_is_frozen_fair_and_has_declared_pairs() -> None:
    manifest = load_manifest()

    assert manifest["manifest_revision"] == 1
    assert manifest["git_checkpoint"] == "84729b17dc6e308547b78a35f1b044ee8ad633b7"
    assert manifest["models"] == EXPECTED_MODELS
    assert manifest["provider_routing"] == EXPECTED_ROUTING
    assert manifest["runtime_settings"]["reasoning_effort"] == "high"
    assert manifest["runtime_settings"]["generation_attempt_limit"] == 3
    assert manifest["runtime_settings"]["roles"] == {
        "case_generation": {"max_tokens": 16_384, "temperature": 0.55, "json_mode": True},
        "private_npc_action": {"max_tokens": 80, "temperature": 0.0, "json_mode": True},
        "private_interview_selection": {"max_tokens": 80, "temperature": 0.0, "json_mode": True},
        "portrayal": {"max_tokens": 220, "temperature": 0.2, "json_mode": True},
    }
    assert [pair["model_order"] for pair in manifest["generation_pairs"]] == [
        ["flash", "pro"], ["pro", "flash"], ["flash", "pro"],
    ]
    assert [(pair["pair_id"], pair["seed"]) for pair in manifest["generation_pairs"]] == [
        ("P1", 2026072101), ("P2", 2026072102), ("P3", 2026072103),
    ]
    assert manifest["generation_pairs"][0]["cast_ids"] == [
        "captain_marcus_drake", "celia_marlowe", "countess_beatrice_harrow",
        "dr_celestine_moreau", "edgar_blackwood", "inspector_elena_hayes",
        "lady_helena_wren", "zara_okonkwo",
    ]
    assert manifest["reserve_pair"]["seed"] == 2026072104
    assert all(len(pair["cast_ids"]) == len(set(pair["cast_ids"])) == 8 for pair in manifest["generation_pairs"])


def test_dry_run_is_sanitized_and_makes_no_provider_calls() -> None:
    summary = dry_run_summary(load_manifest())

    assert summary["provider_calls_made"] == 0
    assert summary["pairs"] == ["P1", "P2", "P3"]
    assert "key" not in json.dumps(summary).lower()


def test_execution_refuses_unverified_or_non_opted_in_traffic() -> None:
    manifest = load_manifest()
    request = build_request(manifest, "pro", task_role="case_generation")
    called = False

    def provider_call(_request: object) -> None:
        nonlocal called
        called = True

    with pytest.raises(ExperimentSafetyError, match="explicit opt-in"):
        execute_with_verified_preflights(
            manifest=manifest, preflight_evidence=_verified_preflights(),
            explicitly_enabled=False, provider_call=provider_call, request=request,
        )
    with pytest.raises(ExperimentSafetyError, match="preflights"):
        execute_with_verified_preflights(
            manifest=manifest,
            preflight_evidence={"pro": _verified_preflights()["pro"]},
            explicitly_enabled=True, provider_call=provider_call, request=request,
        )
    assert called is False


def test_verified_preflight_and_request_are_pinned() -> None:
    manifest = load_manifest()
    verify_preflights(_verified_preflights(), manifest)
    request = build_request(manifest, "flash", task_role="private_npc_action")

    assert request.model == EXPECTED_MODELS["flash"]
    assert dict(request.provider) == EXPECTED_ROUTING
    assert request.reasoning_effort == "high"
    assert request.max_tokens == 80
    assert request.temperature == 0.0
    assert request.json_mode is True


def test_measured_revision_requires_clean_full_git_sha(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []

    class Result:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def clean_run(command, **_kwargs):
        calls.append(command)
        return Result("" if "status" in command else "a" * 40 + "\n")

    monkeypatch.setattr("experiments.deepseek_v4_runner.subprocess.run", clean_run)
    assert resolve_clean_git_sha(tmp_path) == "a" * 40
    assert calls == [
        ["git", "status", "--porcelain", "--untracked-files=all"],
        ["git", "rev-parse", "HEAD"],
    ]

    def dirty_run(command, **_kwargs):
        return Result(" M backend/file.py\n" if "status" in command else "a" * 40)

    monkeypatch.setattr("experiments.deepseek_v4_runner.subprocess.run", dirty_run)
    with pytest.raises(ExperimentSafetyError, match="clean committed"):
        resolve_clean_git_sha(tmp_path)
