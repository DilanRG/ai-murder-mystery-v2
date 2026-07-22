"""Offline safety tests for the paid Stage 2 qualification controller."""

from __future__ import annotations

from copy import deepcopy
import json
import pytest

from experiments.deepseek_v4_runner import ExperimentSafetyError
from experiments.run_stage2_semantic_qualification import (
    EXPERIMENT_REVISION,
    EXPECTED_MODELS,
    EXPECTED_BRANCH,
    STAGE2_PROMPT_REVISION,
    STAGE2_SCHEMA_REVISION,
    _load_checkpoint_records,
    _manifest_fingerprint,
    _reasoning_map,
    load_manifest,
    validate_manifest,
)


def test_stage2_manifest_is_frozen_without_private_or_provider_access() -> None:
    manifest = load_manifest()
    validate_manifest(manifest)
    assert manifest["models"] == EXPECTED_MODELS
    assert all(
        len(manifest["accepted_stage1"][model_key]["compiled_stage_1_fingerprint"])
        == 64
        for model_key in manifest["model_order"]
    )


@pytest.mark.parametrize(
    "path,value",
    [
        (("model_order",), ["pro", "flash"]),
        (("provider_fallbacks",), True),
        (("limits", "stage_2b_max_tokens"), 20_000),
        (("budget", "soft_stop_usd"), "9.00"),
        (("stop_boundary",), "stage4_presentation"),
        (("accepted_stage1", "flash", "compiled_stage_1_fingerprint"), "0" * 64),
    ],
)
def test_manifest_tampering_fails_closed(path: tuple[str, ...], value: object) -> None:
    manifest = deepcopy(load_manifest())
    target = manifest
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ExperimentSafetyError):
        validate_manifest(manifest)


def test_only_declared_stage2_roles_can_reach_measured_controller() -> None:
    roles = _reasoning_map()
    assert roles["stage2_semantic_2a"] == "high"
    assert roles["stage2_semantic_2b"] == "high"
    assert roles["stage2_semantic_2c"] == "high"
    assert roles["stage2_semantic_2a_delta_repair"] is None
    assert roles["stage2_exact_model_preflight"] is None
    assert not any("stage3" in role or "overlay" in role for role in roles)


def test_checkpoint_provenance_and_stage_order_fail_closed(tmp_path) -> None:
    manifest = load_manifest()
    model_key = "flash"
    model = EXPECTED_MODELS[model_key]
    git_sha = "a" * 40
    checkpoint = {
        "schema_version": 1,
        "experiment_revision": EXPERIMENT_REVISION,
        "manifest_fingerprint": _manifest_fingerprint(manifest),
        "branch": EXPECTED_BRANCH,
        "git_sha": git_sha,
        "model_key": model_key,
        "model": model,
        "input_stage_1_fingerprints": manifest["accepted_stage1"][model_key],
        "prompt_revision": STAGE2_PROMPT_REVISION,
        "schema_revision": STAGE2_SCHEMA_REVISION,
        "accepted_stage_records": [],
    }
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    assert _load_checkpoint_records(
        path=path,
        manifest=manifest,
        model_key=model_key,
        model=model,
        git_sha=git_sha,
    ) == []

    checkpoint["git_sha"] = "b" * 40
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(ExperimentSafetyError, match="git_sha provenance mismatch"):
        _load_checkpoint_records(
            path=path,
            manifest=manifest,
            model_key=model_key,
            model=model,
            git_sha=git_sha,
        )
