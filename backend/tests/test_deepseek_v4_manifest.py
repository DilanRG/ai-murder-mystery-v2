"""Offline checks for the frozen, no-traffic DeepSeek V4 experiment contract."""

from __future__ import annotations

from copy import deepcopy
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
    validate_manifest,
    verify_preflights,
)


def _verified_preflights() -> dict[str, object]:
    return {
        key: {
            "experiment_revision": 7,
            "model": slug,
            "actual_model": slug,
            "upstream_provider": "deepseek",
            "transport": "deepseek_direct",
            "is_byok": None,
            "fallback_used": False,
            "accounting_mode": "direct_token_meter",
            "generation_id": f"preflight-{key}",
            "total_external_cost_usd": 0.001,
        }
        for key, slug in EXPECTED_MODELS.items()
    }


def test_manifest_is_frozen_fair_and_has_declared_pairs() -> None:
    manifest = load_manifest()

    assert manifest["manifest_revision"] == 7
    assert manifest["git_checkpoint"] == "0166ca14c80a5e84c1322e93667d71eea1461aa6"
    assert manifest["gateway"] == "deepseek_direct"
    assert manifest["model_fallbacks"] == []
    assert manifest["runtime_settings"]["sampler_defaults"]["top_k"] is None
    assert manifest["reservation_pricing_ceiling_usd_per_million"]["pro"] == {
        "input": 5.0,
        "output": 10.0,
    }
    assert manifest["direct_deepseek_pricing_usd_per_million"]["flash"] == {
        "cache_hit_input": 0.0028,
        "cache_miss_input": 0.14,
        "output": 0.28,
    }
    assert manifest["models"] == EXPECTED_MODELS
    assert manifest["provider_routing"] is EXPECTED_ROUTING is None
    assert manifest["runtime_settings"]["reasoning_effort"] == "high"
    assert manifest["runtime_settings"]["candidate_pipeline_limit"] == 1
    assert manifest["runtime_settings"]["stage_attempt_limit"] == 3
    assert manifest["runtime_settings"]["roles"] == {
        "case_generation_core": {"max_tokens": 20_000, "temperature": 0.55, "json_mode": True},
        "case_generation_evidence": {"max_tokens": 20_000, "temperature": 0.55, "json_mode": True},
        "case_generation_overlays": {"max_tokens": 24_000, "temperature": 0.55, "json_mode": True},
        "case_generation_presentation": {"max_tokens": 8_000, "temperature": 0.2, "json_mode": True},
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


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("P2", "seed", 999),
        ("P3", "cast_ids", ["tampered"] * 8),
        ("R1", "model_order", ["flash", "pro"]),
        ("R1", "activation_rule", "silently retry anything"),
    ],
)
def test_runtime_rejects_any_frozen_pair_catalog_tampering(
    target: str,
    field: str,
    value: object,
) -> None:
    manifest = deepcopy(load_manifest())
    if target == "R1":
        manifest["reserve_pair"][field] = value
    else:
        pair = next(pair for pair in manifest["generation_pairs"] if pair["pair_id"] == target)
        pair[field] = value

    with pytest.raises(ExperimentSafetyError, match="frozen catalog"):
        validate_manifest(manifest)


def test_execution_refuses_unverified_or_non_opted_in_traffic() -> None:
    manifest = load_manifest()
    request = build_request(manifest, "pro", task_role="case_generation_core")
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
    assert request.provider is EXPECTED_ROUTING is None
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
