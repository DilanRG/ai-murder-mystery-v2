from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from experiments.deepseek_v4_runner import ExperimentSafetyError
from experiments.run_stage1_semantic_qualification import (
    EXPECTED_MODELS,
    Stage1QualificationPolicy,
    _load_manifest,
    main,
    validate_manifest,
)
from llm.experiment import ExperimentPolicyError


def _manifest() -> dict[str, object]:
    return _load_manifest()


def test_frozen_qualification_manifest_is_valid() -> None:
    validate_manifest(_manifest())


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("model_order",), ["pro", "flash"]),
        (("models", "flash"), "deepseek-v4-pro"),
        (("limits", "initial_attempts_per_model"), 4),
        (("limits", "delta_repairs_per_parsed_candidate"), 3),
        (("limits", "semantic_plan_max_tokens"), 20_000),
        (("budget", "hard_stop_usd"), "10.00"),
        (("reasoning", "semantic_plan"), "medium"),
        (("stop_boundary",), "complete_case"),
        (("baseline_sha",), "f" * 40),
        (("location_id",), "another_location"),
        (("death_mode",), "suicide"),
        (("provider_fallbacks",), True),
        (("role_assignment_fingerprint",), "0" * 64),
    ],
)
def test_manifest_tampering_fails_closed(
    path: tuple[str, ...], replacement: object
) -> None:
    manifest = deepcopy(_manifest())
    target: dict[str, object] = manifest
    for component in path[:-1]:
        target = target[component]  # type: ignore[assignment]
    target[path[-1]] = replacement

    with pytest.raises(ExperimentSafetyError):
        validate_manifest(manifest)


def test_dry_run_reports_zero_paid_calls(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "experiments.run_stage1_semantic_qualification.qualification_git_identity",
        lambda *, require_clean: ("stage1-semantic-compiler", "a" * 40),
    )
    monkeypatch.setattr(
        "experiments.run_stage1_semantic_qualification.load_direct_api_key",
        lambda: pytest.fail("dry-run must not load credentials"),
    )

    assert main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["paid_calls_made"] == 0
    assert result["model_order"] == ["flash", "pro"]


def test_policy_allows_only_declared_plan_and_repair_reasoning() -> None:
    policy = Stage1QualificationPolicy()
    request = {
        "provider": "deepseek",
        "model": EXPECTED_MODELS["flash"],
        "allow_fallbacks": False,
        "parameters": {"transport": "deepseek_direct"},
    }

    policy.validate_request(**request, reasoning="high")
    policy.validate_request(**request, reasoning="none")
    with pytest.raises(ExperimentPolicyError):
        policy.validate_request(**request, reasoning="medium")
    with pytest.raises(ExperimentPolicyError):
        policy.validate_request(**(request | {"allow_fallbacks": True}), reasoning="high")


def test_manifest_names_a_fresh_ledger_namespace_and_stage2_boundary() -> None:
    manifest = _manifest()
    assert manifest["budget"]["namespace"] == "stage1_semantic_qualification"
    assert manifest["stop_boundary"] == "existing_stage_2_input"

    runner_source = Path(
        "experiments/run_stage1_semantic_qualification.py"
    ).read_text(encoding="utf-8")
    assert "generate_stage1_boundary(" in runner_source
    assert "generate_validated_scenario(" not in runner_source
    assert '"stage_2_requests": 0' in runner_source
