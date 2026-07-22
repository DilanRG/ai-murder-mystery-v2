"""Offline safety tests for the decomposed Stage 2C qualification controller."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json
import subprocess

import pytest

from experiments import run_stage2c_decomposed_qualification as controller
from experiments.deepseek_v4_runner import ExperimentSafetyError


def test_decomposed_manifest_is_frozen_without_provider_access() -> None:
    manifest = controller.load_manifest()
    controller.validate_manifest(manifest)
    assert manifest["models"] == controller.EXPECTED_MODELS
    assert manifest["source_stage2"]["git_sha"] == (
        "d550fb81a23f24c84e7e1aff121aadf1cbd9ae2c"
    )


@pytest.mark.parametrize(
    "path,value",
    [
        (("model_order",), ["pro", "flash"]),
        (("provider_fallbacks",), True),
        (("source_stage2", "git_sha"), "0" * 40),
        (("source_stage2c_revision15", "results_sha256"), "0" * 64),
        (("source_stage2c_revision16", "results_sha256"), "0" * 64),
        (("source_stage2", "accepted_compiled_stage2", "pro", "stage_2b"), "0" * 64),
        (("limits", "stage_2c_p2_max_tokens"), 9_000),
        (("limits", "stage_2c_realization_max_tokens"), 9_000),
        (("reasoning", "stage_2c_realizations"), "high"),
        (("budget", "carry_in_stage2_cost_usd"), "0"),
        (("stop_boundary",), "stage4_presentation"),
    ],
)
def test_decomposed_manifest_tampering_fails_closed(
    path: tuple[str, ...], value: object
) -> None:
    manifest = deepcopy(controller.load_manifest())
    target = manifest
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ExperimentSafetyError):
        controller.validate_manifest(manifest)


def test_only_p2_is_high_reasoning_and_no_stage3_role_exists() -> None:
    roles = controller._reasoning_map()
    assert roles["stage2_semantic_2c_p2"] == "high"
    assert "stage2_semantic_2c_p1" not in roles
    assert roles["stage2_semantic_2c_r1"] is None
    assert roles["stage2_semantic_2c_r2"] is None
    assert "stage2_semantic_2c_p1_delta_repair" not in roles
    assert roles["stage2_semantic_2c_p2_delta_repair"] is None
    assert roles["stage2c_exact_model_preflight"] is None
    assert not any("stage3" in role or "overlay" in role for role in roles)


def _revision16_p1_request_rows(manifest: dict) -> list[dict]:
    source = manifest["source_stage2c_revision16"]
    return [
        {
            "git_sha": source["git_sha"],
            "run_id": f"stage2c-plan-items-{model_key}",
            "task_role": "stage2_semantic_2c_p1",
            "requested_model": model,
            "actual_model": model,
            "transport": "deepseek_direct",
            "fallback_used": False,
            "provider_failover_used": False,
            "result": "success",
            "accounting_status": "measured",
            "total_external_cost_usd": "0.001",
        }
        for model_key, model in controller.EXPECTED_MODELS.items()
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("fallback_used", True),
        ("provider_failover_used", True),
        ("total_external_cost_usd", None),
    ],
)
def test_revision16_p1_reuse_requires_exact_measured_direct_evidence(
    field: str, value: object
) -> None:
    manifest = controller.load_manifest()
    rows = _revision16_p1_request_rows(manifest)
    controller._validate_revision16_request_records(
        source=manifest["source_stage2c_revision16"], request_rows=rows
    )
    rows[0][field] = value
    with pytest.raises(ExperimentSafetyError, match="P1 request evidence mismatched"):
        controller._validate_revision16_request_records(
            source=manifest["source_stage2c_revision16"], request_rows=rows
        )


def test_revision16_source_boundary_rejects_overlay_aliases() -> None:
    manifest = controller.load_manifest()
    rows = _revision16_p1_request_rows(manifest)
    rows.append({"task_role": "npc_overlay_generation"})
    with pytest.raises(ExperimentSafetyError, match="unauthorized Stage 3"):
        controller._validate_revision16_request_records(
            source=manifest["source_stage2c_revision16"], request_rows=rows
        )


def _current_checkpoint(manifest: dict, *, git_sha: str) -> dict:
    return {
        "schema_version": 1,
        "experiment_revision": controller.EXPERIMENT_REVISION,
        "manifest_fingerprint": controller._manifest_fingerprint(manifest),
        "branch": controller.EXPECTED_BRANCH,
        "git_sha": git_sha,
        "model_key": "flash",
        "model": controller.EXPECTED_MODELS["flash"],
        "prompt_revision": controller.STAGE2C_PLAN_ITEMS_PROMPT_REVISION,
        "schema_revision": controller.STAGE2C_PLAN_ITEMS_SCHEMA_REVISION,
        "source_stage2_git_sha": manifest["source_stage2"]["git_sha"],
        "source_stage2_manifest_fingerprint": manifest["source_stage2"]["manifest_fingerprint"],
        "source_stage1_fingerprints": manifest["accepted_stage1"]["flash"],
        "source_stage2_fingerprints": manifest["source_stage2"][
            "accepted_compiled_stage2"
        ]["flash"],
        "source_checkpoint_sha256": "f" * 64,
        "source_stage2c_checkpoint_sha256": manifest["source_stage2c_revision16"][
            "checkpoints"
        ]["flash"]["sha256"],
        "reused_stage_2c_p1_fingerprint": manifest["source_stage2c_revision16"][
            "checkpoints"
        ]["flash"]["accepted_p1_fingerprint"],
        "accepted_stage_records": [],
    }


def test_current_checkpoint_rejects_skip_duplicate_and_provenance_tampering(
    tmp_path,
) -> None:
    manifest = controller.load_manifest()
    git_sha = "a" * 40
    checkpoint = _current_checkpoint(manifest, git_sha=git_sha)
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    assert controller._load_current_records(
        path=path,
        manifest=manifest,
        model_key="flash",
        git_sha=git_sha,
        source_provenance={
            "source_checkpoint_sha256": "f" * 64,
            "source_stage2c_checkpoint_sha256": manifest["source_stage2c_revision16"]["checkpoints"]["flash"]["sha256"],
            "reused_stage_2c_p1_fingerprint": manifest["source_stage2c_revision16"]["checkpoints"]["flash"]["accepted_p1_fingerprint"],
        },
    ) == []

    checkpoint["accepted_stage_records"] = [{"stage": "stage2_semantic_2c_r1"}]
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(ExperimentSafetyError, match="order is invalid"):
        controller._load_current_records(
            path=path,
            manifest=manifest,
            model_key="flash",
            git_sha=git_sha,
            source_provenance={
                "source_checkpoint_sha256": "f" * 64,
                "source_stage2c_checkpoint_sha256": manifest["source_stage2c_revision16"]["checkpoints"]["flash"]["sha256"],
                "reused_stage_2c_p1_fingerprint": manifest["source_stage2c_revision16"]["checkpoints"]["flash"]["accepted_p1_fingerprint"],
            },
        )

    checkpoint["accepted_stage_records"] = [
        {"stage": "stage2_semantic_2c_p2"},
        {"stage": "stage2_semantic_2c_p2"},
    ]
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(ExperimentSafetyError, match="order is invalid"):
        controller._load_current_records(
            path=path,
            manifest=manifest,
            model_key="flash",
            git_sha=git_sha,
            source_provenance={
                "source_checkpoint_sha256": "f" * 64,
                "source_stage2c_checkpoint_sha256": manifest["source_stage2c_revision16"]["checkpoints"]["flash"]["sha256"],
                "reused_stage_2c_p1_fingerprint": manifest["source_stage2c_revision16"]["checkpoints"]["flash"]["accepted_p1_fingerprint"],
            },
        )

    checkpoint = _current_checkpoint(manifest, git_sha=git_sha)
    checkpoint["source_stage2_git_sha"] = "b" * 40
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(ExperimentSafetyError, match="source_stage2_git_sha mismatched"):
        controller._load_current_records(
            path=path,
            manifest=manifest,
            model_key="flash",
            git_sha=git_sha,
            source_provenance={
                "source_checkpoint_sha256": "f" * 64,
                "source_stage2c_checkpoint_sha256": manifest["source_stage2c_revision16"]["checkpoints"]["flash"]["sha256"],
                "reused_stage_2c_p1_fingerprint": manifest["source_stage2c_revision16"]["checkpoints"]["flash"]["accepted_p1_fingerprint"],
            },
        )

    checkpoint = _current_checkpoint(manifest, git_sha=git_sha)
    checkpoint["source_checkpoint_sha256"] = "0" * 64
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(ExperimentSafetyError, match="source_checkpoint_sha256 mismatched"):
        controller._load_current_records(
            path=path,
            manifest=manifest,
            model_key="flash",
            git_sha=git_sha,
            source_provenance={
                "source_checkpoint_sha256": "f" * 64,
                "source_stage2c_checkpoint_sha256": manifest["source_stage2c_revision16"]["checkpoints"]["flash"]["sha256"],
                "reused_stage_2c_p1_fingerprint": manifest["source_stage2c_revision16"]["checkpoints"]["flash"]["accepted_p1_fingerprint"],
            },
        )


def test_historical_loader_reuses_only_exact_prefix_and_excludes_flash_suffix(
    monkeypatch,
) -> None:
    manifest = controller.load_manifest()
    source = manifest["source_stage2"]
    expected = source["accepted_compiled_stage2"]["flash"]
    records = [
        {
            "stage": stage,
            "semantic_candidate_fingerprint": f"semantic-{index}",
            "compiled_fingerprint": (
                expected["stage_2a"]
                if stage == "stage2_semantic_2a"
                else expected["stage_2b"]
                if stage == "stage2_semantic_2b"
                else f"compiled-{index}"
            ),
            "model_authored_document": {"semantic": index},
            "document": {"compiled": index},
        }
        for index, stage in enumerate(
            (*controller.SOURCE_PREFIX_STAGES, "stage2_semantic_2c", "stage2_assembled_stage3_ready")
        )
    ]
    checkpoint = {
        "schema_version": 1,
        "experiment_revision": source["experiment_revision"],
        "manifest_fingerprint": source["manifest_fingerprint"],
        "branch": source["branch"],
        "git_sha": source["git_sha"],
        "model_key": "flash",
        "model": controller.EXPECTED_MODELS["flash"],
        "input_stage_1_fingerprints": manifest["accepted_stage1"]["flash"],
        "prompt_revision": source["prompt_revision"],
        "schema_revision": source["schema_revision"],
        "accepted_stage_records": records,
    }
    p1_fingerprint = manifest["source_stage2c_revision16"]["checkpoints"][
        "flash"
    ]["accepted_p1_fingerprint"]
    p1_record = {
        "stage": "stage2_semantic_2c_p1",
        "semantic_candidate_fingerprint": p1_fingerprint,
        "compiled_fingerprint": p1_fingerprint,
        "model_authored_document": {"p1": 1},
        "document": {"p1": 1},
    }
    p1_checkpoint = {"accepted_stage_records": [p1_record]}

    def fake_load(_path, *, label):
        if "manifest" in label:
            return {}
        if "Revision 16 P1 checkpoint" in label:
            return p1_checkpoint
        return checkpoint

    def fake_fingerprint(value):
        if "p1" in value:
            return p1_fingerprint
        if "semantic" in value:
            return f"semantic-{value['semantic']}"
        index = value["compiled"]
        stage = records[index]["stage"]
        if stage == "stage2_semantic_2a":
            return expected["stage_2a"]
        if stage == "stage2_semantic_2b":
            return expected["stage_2b"]
        return f"compiled-{index}"

    monkeypatch.setattr(controller, "_load_json", fake_load)
    monkeypatch.setattr(controller, "_manifest_fingerprint", lambda _value: source["manifest_fingerprint"])
    monkeypatch.setattr(controller, "content_fingerprint", fake_fingerprint)
    monkeypatch.setattr(
        controller.Stage2CP1Candidate,
        "model_validate",
        lambda value: value,
    )
    monkeypatch.setattr(controller, "verify_stage1_artifact", lambda *_args: {})
    monkeypatch.setattr(controller, "_file_fingerprint", lambda _path: "f" * 64)
    prefix, provenance = controller.verify_historical_prefix(manifest, "flash")
    assert [row["stage"] for row in prefix] == [
        *controller.SOURCE_PREFIX_STAGES,
        "stage2_semantic_2c_p1",
    ]
    assert provenance["reused_stage_2c_p1_fingerprint"] == p1_fingerprint
    assert provenance["historical_suffix_excluded"] == [
        "stage2_semantic_2c",
        "stage2_assembled_stage3_ready",
    ]


def test_budget_policy_carries_forward_through_revision16_cost() -> None:
    manifest = controller.load_manifest()
    policy = controller._budget_policy(manifest)
    assert policy.soft_stop_usd == Decimal("8.41523668")
    assert policy.hard_stop_usd == Decimal("9.41523668")


def test_qualification_commit_must_descend_from_frozen_baseline(monkeypatch) -> None:
    def fake_git(*args: str) -> str:
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "development"
        if args == ("rev-parse", "HEAD"):
            return "b" * 40
        if args[:2] == ("merge-base", "--is-ancestor"):
            raise subprocess.CalledProcessError(1, ["git", *args])
        raise AssertionError(args)

    monkeypatch.setattr(controller, "_git_output", fake_git)
    with pytest.raises(ExperimentSafetyError, match="does not descend"):
        controller.qualification_git_identity(require_clean=False)


def test_request_history_is_exact_commit_bound_and_duplicate_safe(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "requests.jsonl"
    rows = [
        {
            "request_id": f"request-{index}",
            "git_sha": "a" * 40,
            "run_id": "stage2c-p2-extended-flash",
            "task_role": "stage2_semantic_2c_p2",
            "total_external_cost_usd": "0.001",
        }
        for index in range(2)
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(controller, "REQUESTS_PATH", path)
    metrics = controller._request_metrics(model_key="flash", git_sha="a" * 40)
    assert metrics["request_records"] == 2
    assert metrics["locally_estimated_cost_usd"] == "0.002"

    rows[1]["request_id"] = rows[0]["request_id"]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(ExperimentSafetyError, match="duplicated"):
        controller._run_request_records(model_key="flash", git_sha="a" * 40)


def test_terminal_results_prevent_hidden_attempt_budget_reset(
    tmp_path, monkeypatch
) -> None:
    manifest = controller.load_manifest()
    git_sha = "a" * 40
    path = tmp_path / "results.json"
    document = {
        "schema_version": 1,
        "experiment_revision": controller.EXPERIMENT_REVISION,
        "manifest_fingerprint": controller._manifest_fingerprint(manifest),
        "git_sha": git_sha,
        "model_results": [
            {
                "model_key": "pro",
                "status": "failed",
                "failure_code": "semantic_validation_failed",
            }
        ],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(controller, "RESULTS_PATH", path)
    loaded = controller._existing_results(manifest=manifest, git_sha=git_sha)
    assert loaded["model_results"][0]["status"] == "failed"

    document["git_sha"] = "b" * 40
    path.write_text(json.dumps(document), encoding="utf-8")
    assert controller._existing_results(manifest=manifest, git_sha=git_sha) == {
        "model_results": []
    }


def test_terminal_results_reject_duplicate_model_rows(tmp_path, monkeypatch) -> None:
    manifest = controller.load_manifest()
    git_sha = "a" * 40
    row = {
        "model_key": "flash",
        "status": "failed",
        "failure_code": "semantic_validation_failed",
    }
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment_revision": controller.EXPERIMENT_REVISION,
                "manifest_fingerprint": controller._manifest_fingerprint(manifest),
                "git_sha": git_sha,
                "model_results": [row, row],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(controller, "RESULTS_PATH", path)
    with pytest.raises(ExperimentSafetyError, match="models are invalid"):
        controller._existing_results(manifest=manifest, git_sha=git_sha)


def test_terminal_failed_result_requires_exact_source_provenance() -> None:
    manifest = controller.load_manifest()
    source_provenance = {
        "source_checkpoint": "checkpoint.json",
        "source_checkpoint_sha256": "f" * 64,
        "source_stage2c_checkpoint": "checkpoint-p1.json",
        "source_stage2c_checkpoint_sha256": manifest["source_stage2c_revision16"][
            "checkpoints"
        ]["flash"]["sha256"],
        "source_git_sha": manifest["source_stage2"]["git_sha"],
        "source_stage_1_fingerprints": manifest["accepted_stage1"]["flash"],
        "reused_compiled_stage_2a_fingerprint": manifest["source_stage2"][
            "accepted_compiled_stage2"
        ]["flash"]["stage_2a"],
        "reused_compiled_stage_2b_fingerprint": manifest["source_stage2"][
            "accepted_compiled_stage2"
        ]["flash"]["stage_2b"],
        "reused_stage_2c_p1_fingerprint": manifest["source_stage2c_revision16"][
            "checkpoints"
        ]["flash"]["accepted_p1_fingerprint"],
        "revision16_suffix_excluded": [
            "stage2_semantic_2c_p2",
            "stage2_semantic_2c_p",
            "stage2_semantic_2c_r1",
            "stage2_semantic_2c_r2",
            "stage2_semantic_2c",
            "stage2_assembled_stage3_ready",
        ],
        "historical_suffix_excluded": [
            "stage2_semantic_2c",
            "stage2_assembled_stage3_ready",
        ],
    }
    row = {
        "model_key": "flash",
        "model": controller.EXPECTED_MODELS["flash"],
        "status": "failed",
        "failure_code": "semantic_validation_failed",
        **source_provenance,
    }
    controller._validate_terminal_result(
        manifest=manifest,
        git_sha="a" * 40,
        row=row,
        source_provenance=source_provenance,
    )
    row["source_checkpoint_sha256"] = "0" * 64
    with pytest.raises(ExperimentSafetyError, match="source provenance mismatched"):
        controller._validate_terminal_result(
            manifest=manifest,
            git_sha="a" * 40,
            row=row,
            source_provenance=source_provenance,
        )


def test_terminal_failure_never_suppresses_bounded_resume() -> None:
    assert not controller._terminal_result_may_skip(
        {"status": "failed", "failure_code": "semantic_validation_failed"}
    )
    assert controller._terminal_result_may_skip(
        {"status": "passed_stage_2_stage3_ready"}
    )


def test_terminal_pass_requires_measured_exact_model_p_r1_r2_requests(
    tmp_path, monkeypatch
) -> None:
    git_sha = "a" * 40
    model = controller.EXPECTED_MODELS["flash"]
    roles = [
        "stage2_semantic_2c_p2",
        "stage2_semantic_2c_r1",
        "stage2_semantic_2c_r2",
    ]
    records = [
        {
            "request_id": f"request-{index}",
            "git_sha": git_sha,
            "run_id": "stage2c-p2-extended-flash",
            "task_role": role,
            "requested_model": model,
            "actual_model": model,
            "transport": "deepseek_direct",
            "fallback_used": False,
            "provider_failover_used": False,
            "result": "success",
            "accounting_status": "measured",
            "total_external_cost_usd": 0.001,
        }
        for index, role in enumerate(roles)
    ]
    path = tmp_path / "requests.jsonl"
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(controller, "REQUESTS_PATH", path)
    row = {
        "request_records": 3,
        "locally_estimated_cost_usd": "0.003",
        "request_roles": roles,
    }
    controller._validate_pass_request_evidence(
        row=row, model_key="flash", git_sha=git_sha
    )

    path.write_text(
        "\n".join(json.dumps(record) for record in records[:2]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ExperimentSafetyError, match="lacks complete"):
        controller._validate_pass_request_evidence(
            row=row, model_key="flash", git_sha=git_sha
        )

    records[2]["actual_model"] = controller.EXPECTED_MODELS["pro"]
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ExperimentSafetyError, match="evidence is untrusted"):
        controller._validate_pass_request_evidence(
            row=row, model_key="flash", git_sha=git_sha
        )


def test_terminal_pass_cannot_skip_without_private_accepted_artifact(
    tmp_path, monkeypatch
) -> None:
    manifest = controller.load_manifest()
    source_provenance = {
        "source_checkpoint": "checkpoint.json",
        "source_checkpoint_sha256": "f" * 64,
        "source_stage2c_checkpoint": "checkpoint-p1.json",
        "source_stage2c_checkpoint_sha256": manifest["source_stage2c_revision16"][
            "checkpoints"
        ]["flash"]["sha256"],
        "source_git_sha": manifest["source_stage2"]["git_sha"],
        "source_stage_1_fingerprints": manifest["accepted_stage1"]["flash"],
        "reused_compiled_stage_2a_fingerprint": manifest["source_stage2"][
            "accepted_compiled_stage2"
        ]["flash"]["stage_2a"],
        "reused_compiled_stage_2b_fingerprint": manifest["source_stage2"][
            "accepted_compiled_stage2"
        ]["flash"]["stage_2b"],
        "reused_stage_2c_p1_fingerprint": manifest["source_stage2c_revision16"][
            "checkpoints"
        ]["flash"]["accepted_p1_fingerprint"],
        "revision16_suffix_excluded": [
            "stage2_semantic_2c_p2",
            "stage2_semantic_2c_p",
            "stage2_semantic_2c_r1",
            "stage2_semantic_2c_r2",
            "stage2_semantic_2c",
            "stage2_assembled_stage3_ready",
        ],
        "historical_suffix_excluded": [
            "stage2_semantic_2c",
            "stage2_assembled_stage3_ready",
        ],
    }
    row = {
        "model_key": "flash",
        "model": controller.EXPECTED_MODELS["flash"],
        "status": "passed_stage_2_stage3_ready",
        **source_provenance,
    }
    monkeypatch.setattr(controller, "ARTIFACT_ROOT", tmp_path)
    with pytest.raises(ExperimentSafetyError, match="unavailable or malformed"):
        controller._validate_terminal_result(
            manifest=manifest,
            git_sha="a" * 40,
            row=row,
            source_provenance=source_provenance,
        )
