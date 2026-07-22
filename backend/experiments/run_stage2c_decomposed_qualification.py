"""Qualify decomposed Stage 2C from exact accepted Revision 14 prefixes."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from experiments.deepseek_v4_runtime import DeepSeekRequestObserver, RunContext, load_direct_api_key
from experiments.deepseek_v4_runner import ExperimentSafetyError
from experiments.run_stage2_semantic_qualification import (
    Stage2ProviderPolicy,
    _append_jsonl,
    _atomic_json,
    _git_output,
    _json_ready,
    _load_json,
    _safe_callback,
    verify_stage1_artifact,
)
from game.case_generation import GeneratedCrimeTimelineStage
from game.content import load_location
from game.stage1_semantic import content_fingerprint
from game.stage2_semantic import (
    QUALIFICATION_POLICY,
    STAGE2C_PLAN_MAX_TOKENS,
    STAGE2C_REALIZATION_MAX_TOKENS,
    STAGE2_DELTA_REPAIR_MAX_TOKENS,
    STAGE2C_PLAN_ITEMS_PROMPT_REVISION,
    STAGE2C_PLAN_ITEMS_SCHEMA_REVISION,
    STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
    DecomposedStage2CandidateArtifact,
    Stage2CP1Candidate,
    Stage2CP2Candidate,
    Stage2CPlanCandidate,
    Stage2SemanticError,
    assemble_stage2c_plan_candidate,
    generate_stage2_boundary,
)
from llm.client import LLMClient, LLMMessage, LLMProviderError
from llm.experiment import BudgetStop, DeepSeekExperimentLedger, ExperimentPolicyError, LedgerIntegrityError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
MANIFEST_PATH = Path(__file__).with_name("stage2c_decomposed_qualification_manifest.json")
SOURCE_MANIFEST_PATH = Path(__file__).with_name("stage2_semantic_qualification_manifest.json")
SOURCE_ROOT = REPOSITORY_ROOT / ".private" / "stage2_semantic_qualification"
REVISION15_ROOT = REPOSITORY_ROOT / ".private" / "stage2c_decomposed_qualification"
ARTIFACT_ROOT = REPOSITORY_ROOT / ".private" / "stage2c_plan_items_qualification"
ATTEMPTS_PATH = ARTIFACT_ROOT / "attempts.jsonl"
REQUESTS_PATH = ARTIFACT_ROOT / "requests.jsonl"
LEDGER_PATH = ARTIFACT_ROOT / "cost_ledger.jsonl"
PLAN_PATH = ARTIFACT_ROOT / "qualification_plan.json"
RESULTS_PATH = ARTIFACT_ROOT / "qualification_results.json"
PREFLIGHTS_PATH = ARTIFACT_ROOT / "verified_preflights.json"
EXPECTED_BRANCH = "development"
EXPECTED_MODELS = {"flash": "deepseek-v4-flash", "pro": "deepseek-v4-pro"}
EXPERIMENT_REVISION = 16
SOURCE_PREFIX_STAGES = (
    "stage2_semantic_2a_route_1",
    "stage2_semantic_2a_route_2",
    "stage2_semantic_2a",
    "stage2_semantic_2b",
)
CURRENT_CHECKPOINT_STAGES = (
    "stage2_semantic_2c_p1",
    "stage2_semantic_2c_p2",
    "stage2_semantic_2c_p",
    "stage2_semantic_2c_r1",
    "stage2_semantic_2c_r2",
    "stage2_semantic_2c",
    "stage2_assembled_stage3_ready",
)


def _manifest_fingerprint(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_fingerprint(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ExperimentSafetyError(f"required private artifact is unavailable: {path.name}") from error


def load_manifest() -> dict[str, Any]:
    return _load_json(MANIFEST_PATH, label="decomposed Stage 2C qualification manifest")


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != 1 or manifest.get("experiment_revision") != EXPERIMENT_REVISION:
        raise ExperimentSafetyError("unexpected decomposed Stage 2C experiment revision")
    if manifest.get("branch") != EXPECTED_BRANCH:
        raise ExperimentSafetyError("decomposed Stage 2C branch changed")
    if manifest.get("development_baseline_sha") != "a2f76a33649b0a87c84ea22b5e4f14359c80cca3":
        raise ExperimentSafetyError("development baseline changed")
    if manifest.get("prompt_revision") != STAGE2C_PLAN_ITEMS_PROMPT_REVISION or manifest.get("schema_revision") != STAGE2C_PLAN_ITEMS_SCHEMA_REVISION:
        raise ExperimentSafetyError("decomposed Stage 2C prompt or schema revision differs from code")
    if manifest.get("transport") != "deepseek_direct" or manifest.get("provider_fallbacks") is not False:
        raise ExperimentSafetyError("qualification requires direct DeepSeek with no fallback")
    if manifest.get("model_order") != ["flash", "pro"] or manifest.get("models") != EXPECTED_MODELS:
        raise ExperimentSafetyError("exact model order or identifiers changed")
    source = manifest.get("source_stage2")
    if not isinstance(source, Mapping) or {
        "experiment_revision": source.get("experiment_revision"),
        "git_sha": source.get("git_sha"),
        "branch": source.get("branch"),
        "manifest_fingerprint": source.get("manifest_fingerprint"),
        "prompt_revision": source.get("prompt_revision"),
        "schema_revision": source.get("schema_revision"),
    } != {
        "experiment_revision": 14,
        "git_sha": "d550fb81a23f24c84e7e1aff121aadf1cbd9ae2c",
        "branch": "stage2-semantic-compiler",
        "manifest_fingerprint": "2cdc6e86b5391efb279903f137b08cdc1e87a25a423b5bf5cdcc6761d32d2b64",
        "prompt_revision": "stage2-semantic-v3",
        "schema_revision": "stage2-semantic-schema-v2",
    }:
        raise ExperimentSafetyError("historical Stage 2 provenance changed")
    expected_compiled = {
        "flash": {
            "stage_2a": "40b6c23b2af535f4f0e8e115477d747a931c1d9fd600146734012692ccf499d3",
            "stage_2b": "c480ce74c4c1d739a22a3a7339bcdd2b781d5edbf6fc1ace858402582bd87b3f",
        },
        "pro": {
            "stage_2a": "7fe0015aa956086ffbf7377cb93bd9976efa917f673ba9544f9fe9b4128dfa76",
            "stage_2b": "74ca4dcde3484d1fe6280b4ecb82eabbe4bcf08cf4034de81fad21af03a0e2ae",
        },
    }
    if source.get("accepted_compiled_stage2") != expected_compiled:
        raise ExperimentSafetyError("accepted Stage 2A/2B fingerprints changed")
    if manifest.get("source_stage2c_revision15") != {
        "git_sha": "f723042780f77a5c85ccbb615d80791978f207cf",
        "manifest_fingerprint": "8b0cbfe7a3ef1176eb669b64aa6b806e24f7b78feae341a7a8dfa2d521070324",
        "results_sha256": "089e5da9edd1fa3d302f0245ab2a672e118f2755e9c128792d762b22fb7b036f",
        "ledger_sha256": "16268bcfaa8693fbe91317efbba7c5af5310a4f1f708fd089539f9b6f67b2b5b",
        "settled_cost_usd": "0.01158109",
        "cumulative_stage2_cost_usd": "0.07213454",
        "status": "completed_with_failures",
        "stage_3_requests": 0,
    }:
        raise ExperimentSafetyError("Revision 15 baseline provenance changed")
    expected_limits = {
        "initial_attempts_per_substage_per_model": 3,
        "delta_repairs_per_parsed_candidate": 2,
        "stage_2c_plan_max_tokens": STAGE2C_PLAN_MAX_TOKENS,
        "stage_2c_realization_max_tokens": STAGE2C_REALIZATION_MAX_TOKENS,
        "syntax_repair_max_tokens": STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
        "delta_repair_max_tokens": STAGE2_DELTA_REPAIR_MAX_TOKENS,
    }
    if manifest.get("limits") != expected_limits:
        raise ExperimentSafetyError("Stage 2C output or retry limits changed")
    if manifest.get("reasoning") != {
        "stage_2c_plan_items": "high",
        "stage_2c_realizations": "disabled",
        "syntax_repair": "disabled",
        "delta_repair": "disabled",
    }:
        raise ExperimentSafetyError("Stage 2C reasoning policy changed")
    if manifest.get("budget") != {
        "namespace": "stage2c_plan_items_qualification",
        "carry_in_stage2_cost_usd": "0.07213454",
        "cumulative_soft_stop_usd": "8.50",
        "cumulative_hard_stop_usd": "9.50",
        "uncertainty_reserve_usd": "0.50",
    }:
        raise ExperimentSafetyError("decomposed Stage 2C budget policy changed")
    if manifest.get("stop_boundary") != "stage3_private_overlays":
        raise ExperimentSafetyError("Stage 3 stop boundary changed")


def verify_revision15_baseline(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Prove the observed Revision 15 failures before starting a new ledger."""

    source = manifest["source_stage2c_revision15"]
    results_path = REVISION15_ROOT / "qualification_results.json"
    ledger_path = REVISION15_ROOT / "cost_ledger.jsonl"
    if _file_fingerprint(results_path) != source["results_sha256"]:
        raise ExperimentSafetyError("Revision 15 result artifact fingerprint mismatched")
    if _file_fingerprint(ledger_path) != source["ledger_sha256"]:
        raise ExperimentSafetyError("Revision 15 ledger fingerprint mismatched")
    results = _load_json(results_path, label="Revision 15 qualification results")
    if (
        results.get("schema_version") != 1
        or results.get("experiment_revision") != 15
        or results.get("git_sha") != source["git_sha"]
        or results.get("manifest_fingerprint") != source["manifest_fingerprint"]
        or results.get("status") != source["status"]
        or results.get("stage_3_requests") != source["stage_3_requests"]
        or results.get("cumulative_stage2_estimated_cost_usd")
        != source["cumulative_stage2_cost_usd"]
        or not isinstance(results.get("budget"), dict)
        or results["budget"].get("settled_usd") != source["settled_cost_usd"]
        or results["budget"].get("open_reservations") != 0
    ):
        raise ExperimentSafetyError("Revision 15 result disposition mismatched")
    dispositions = {
        str(row.get("model_key")): (row.get("status"), row.get("failure_code"))
        for row in results.get("model_results", [])
        if isinstance(row, dict)
    }
    if dispositions != {
        "flash": ("failed", "semantic_validation_failed"),
        "pro": ("failed", "output_truncated"),
    }:
        raise ExperimentSafetyError("Revision 15 model failures were reinterpreted")
    return results


def qualification_git_identity(*, require_clean: bool) -> tuple[str, str]:
    branch = _git_output("rev-parse", "--abbrev-ref", "HEAD")
    sha = _git_output("rev-parse", "HEAD")
    if branch != EXPECTED_BRANCH:
        raise ExperimentSafetyError("qualification is running from the wrong branch")
    try:
        _git_output(
            "merge-base",
            "--is-ancestor",
            "a2f76a33649b0a87c84ea22b5e4f14359c80cca3",
            sha,
        )
    except subprocess.CalledProcessError as error:
        raise ExperimentSafetyError(
            "qualification commit does not descend from the frozen development baseline"
        ) from error
    if require_clean and _git_output("status", "--porcelain=v1"):
        raise ExperimentSafetyError("paid qualification requires a clean exact commit")
    return branch, sha


def verify_historical_prefix(
    manifest: Mapping[str, Any], model_key: str
) -> tuple[list[dict[str, object]], dict[str, object]]:
    source = manifest["source_stage2"]
    old_manifest = _load_json(SOURCE_MANIFEST_PATH, label="Revision 14 source manifest")
    if _manifest_fingerprint(old_manifest) != source["manifest_fingerprint"]:
        raise ExperimentSafetyError("Revision 14 manifest fingerprint mismatched")
    verify_stage1_artifact(manifest, model_key)
    checkpoint_name = source["checkpoints"].get(model_key)
    if not isinstance(checkpoint_name, str):
        raise ExperimentSafetyError(f"{model_key} source checkpoint name is unavailable")
    checkpoint_path = SOURCE_ROOT / checkpoint_name
    checkpoint = _load_json(checkpoint_path, label=f"{model_key} Revision 14 checkpoint")
    expected_header = {
        "schema_version": 1,
        "experiment_revision": source["experiment_revision"],
        "manifest_fingerprint": source["manifest_fingerprint"],
        "branch": source["branch"],
        "git_sha": source["git_sha"],
        "model_key": model_key,
        "model": EXPECTED_MODELS[model_key],
        "input_stage_1_fingerprints": manifest["accepted_stage1"][model_key],
        "prompt_revision": source["prompt_revision"],
        "schema_revision": source["schema_revision"],
    }
    for key, expected in expected_header.items():
        if checkpoint.get(key) != expected:
            raise ExperimentSafetyError(f"{model_key} historical checkpoint {key} mismatched")
    records = checkpoint.get("accepted_stage_records")
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ExperimentSafetyError(f"{model_key} historical checkpoint records are malformed")
    stages = [str(row.get("stage", "")) for row in records]
    if stages[: len(SOURCE_PREFIX_STAGES)] != list(SOURCE_PREFIX_STAGES):
        raise ExperimentSafetyError(f"{model_key} historical Stage 2 prefix is noncontiguous")
    if len(set(stages)) != len(stages):
        raise ExperimentSafetyError(f"{model_key} historical checkpoint has duplicate stages")
    prefix = [dict(row) for row in records[: len(SOURCE_PREFIX_STAGES)]]
    for record in prefix:
        authored = record.get("model_authored_document")
        compiled = record.get("document")
        if record.get("semantic_candidate_fingerprint") != content_fingerprint(authored):
            raise ExperimentSafetyError(f"{model_key} historical semantic fingerprint mismatched")
        if record.get("compiled_fingerprint") != content_fingerprint(compiled):
            raise ExperimentSafetyError(f"{model_key} historical compiled fingerprint mismatched")
    expected = source["accepted_compiled_stage2"][model_key]
    if prefix[2].get("compiled_fingerprint") != expected["stage_2a"] or prefix[3].get("compiled_fingerprint") != expected["stage_2b"]:
        raise ExperimentSafetyError(f"{model_key} accepted Stage 2A/2B fingerprint mismatched")
    return prefix, {
        "source_checkpoint": checkpoint_name,
        "source_checkpoint_sha256": _file_fingerprint(checkpoint_path),
        "source_git_sha": source["git_sha"],
        "source_stage_1_fingerprints": manifest["accepted_stage1"][model_key],
        "reused_compiled_stage_2a_fingerprint": expected["stage_2a"],
        "reused_compiled_stage_2b_fingerprint": expected["stage_2b"],
        "historical_suffix_excluded": stages[len(SOURCE_PREFIX_STAGES) :],
    }


def _reasoning_map() -> dict[str, str | None]:
    result: dict[str, str | None] = {
        "stage2_semantic_2c_p1": "high",
        "stage2_semantic_2c_p2": "high",
        "stage2_semantic_2c_r1": None,
        "stage2_semantic_2c_r2": None,
        "stage2c_exact_model_preflight": None,
    }
    for role in (
        "stage2_semantic_2c_p1",
        "stage2_semantic_2c_p2",
        "stage2_semantic_2c_r1",
        "stage2_semantic_2c_r2",
    ):
        result[f"{role}_syntax_repair"] = None
        result[f"{role}_delta_repair"] = None
    return result


def _client(
    *, api_key: str, model: str, observer: DeepSeekRequestObserver, reasoning: str | None
) -> LLMClient:
    if reasoning == "high":
        limits = {
            "stage2_semantic_2c_p1": STAGE2C_PLAN_MAX_TOKENS,
            "stage2_semantic_2c_p2": STAGE2C_PLAN_MAX_TOKENS,
        }
        max_tokens = STAGE2C_PLAN_MAX_TOKENS
    else:
        limits = {
            "stage2_semantic_2c_p1_syntax_repair": STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
            "stage2_semantic_2c_p1_delta_repair": STAGE2_DELTA_REPAIR_MAX_TOKENS,
            "stage2_semantic_2c_p2_syntax_repair": STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
            "stage2_semantic_2c_p2_delta_repair": STAGE2_DELTA_REPAIR_MAX_TOKENS,
            "stage2_semantic_2c_r1": STAGE2C_REALIZATION_MAX_TOKENS,
            "stage2_semantic_2c_r2": STAGE2C_REALIZATION_MAX_TOKENS,
            "stage2_semantic_2c_r1_syntax_repair": STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
            "stage2_semantic_2c_r2_syntax_repair": STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
            "stage2_semantic_2c_r1_delta_repair": STAGE2_DELTA_REPAIR_MAX_TOKENS,
            "stage2_semantic_2c_r2_delta_repair": STAGE2_DELTA_REPAIR_MAX_TOKENS,
            "stage2c_exact_model_preflight": 8,
        }
        max_tokens = STAGE2_SYNTAX_REPAIR_MAX_TOKENS
    return LLMClient(
        api_key=api_key,
        model=model,
        transport="deepseek_direct",
        reasoning_effort=reasoning,
        request_observer=_safe_callback(observer),
        temperature=0.45 if reasoning else 0.0,
        top_p=0.95 if reasoning else 1.0,
        top_k=None,
        max_tokens=max_tokens,
        task_max_tokens=limits,
    )


def _checkpoint_path(model_key: str, git_sha: str) -> Path:
    return ARTIFACT_ROOT / f"checkpoint_{model_key}_{git_sha}.json"


def _load_current_records(
    *, path: Path, manifest: Mapping[str, Any], model_key: str, git_sha: str,
    source_provenance: Mapping[str, Any],
) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    value = _load_json(path, label=f"{model_key} decomposed Stage 2C checkpoint")
    expected_header = {
        "schema_version": 1,
        "experiment_revision": EXPERIMENT_REVISION,
        "manifest_fingerprint": _manifest_fingerprint(manifest),
        "branch": EXPECTED_BRANCH,
        "git_sha": git_sha,
        "model_key": model_key,
        "model": EXPECTED_MODELS[model_key],
        "prompt_revision": STAGE2C_PLAN_ITEMS_PROMPT_REVISION,
        "schema_revision": STAGE2C_PLAN_ITEMS_SCHEMA_REVISION,
        "source_stage2_git_sha": manifest["source_stage2"]["git_sha"],
        "source_stage2_manifest_fingerprint": manifest["source_stage2"]["manifest_fingerprint"],
        "source_stage1_fingerprints": manifest["accepted_stage1"][model_key],
        "source_stage2_fingerprints": manifest["source_stage2"]["accepted_compiled_stage2"][model_key],
        "source_checkpoint_sha256": source_provenance["source_checkpoint_sha256"],
    }
    for key, expected in expected_header.items():
        if value.get(key) != expected:
            raise ExperimentSafetyError(f"{model_key} current checkpoint {key} mismatched")
    records = value.get("accepted_stage_records")
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ExperimentSafetyError(f"{model_key} current checkpoint records are malformed")
    stages = [str(row.get("stage", "")) for row in records]
    if stages != list(CURRENT_CHECKPOINT_STAGES[: len(stages)]) or len(stages) > len(CURRENT_CHECKPOINT_STAGES):
        raise ExperimentSafetyError(f"{model_key} current checkpoint order is invalid")
    for row in records:
        if row.get("stage") == "stage2_assembled_stage3_ready":
            document = row.get("document")
            if not isinstance(document, dict) or row.get("stage_fingerprint") != document.get("artifact_fingerprint"):
                raise ExperimentSafetyError(f"{model_key} assembled checkpoint fingerprint mismatched")
            continue
        if row.get("semantic_candidate_fingerprint") != content_fingerprint(row.get("model_authored_document")):
            raise ExperimentSafetyError(f"{model_key} checkpoint semantic fingerprint mismatched")
        if row.get("compiled_fingerprint") != content_fingerprint(row.get("document")):
            raise ExperimentSafetyError(f"{model_key} checkpoint compiled fingerprint mismatched")
    return [dict(row) for row in records]


def _budget_policy(manifest: Mapping[str, Any]) -> Stage2ProviderPolicy:
    budget = manifest["budget"]
    carry = Decimal(str(budget["carry_in_stage2_cost_usd"]))
    return Stage2ProviderPolicy(
        soft_stop_usd=Decimal(str(budget["cumulative_soft_stop_usd"])) - carry,
        hard_stop_usd=Decimal(str(budget["cumulative_hard_stop_usd"])) - carry,
        uncertainty_reserve_usd=Decimal(str(budget["uncertainty_reserve_usd"])),
    )


def _run_request_records(*, model_key: str, git_sha: str) -> list[dict[str, Any]]:
    if not REQUESTS_PATH.is_file():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in REQUESTS_PATH.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("request record is not an object")
            if (
                value.get("git_sha") == git_sha
                and value.get("run_id") == f"stage2c-plan-items-{model_key}"
            ):
                records.append(value)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ExperimentSafetyError("decomposed Stage 2C request metrics are malformed") from error
    request_ids = [str(row.get("request_id", "")) for row in records]
    if not all(request_ids) or len(request_ids) != len(set(request_ids)):
        raise ExperimentSafetyError("decomposed Stage 2C request metrics are duplicated")
    return records


def _request_metrics(*, model_key: str, git_sha: str) -> dict[str, object]:
    records = _run_request_records(model_key=model_key, git_sha=git_sha)
    return {
        "request_records": len(records),
        "locally_estimated_cost_usd": format(
            sum(
                (Decimal(str(row.get("total_external_cost_usd", 0))) for row in records),
                Decimal("0"),
            ),
            "f",
        ),
        "request_roles": sorted({str(row.get("task_role", "")) for row in records}),
    }


def _validate_pass_request_evidence(
    *, row: Mapping[str, Any], model_key: str, git_sha: str
) -> None:
    records = _run_request_records(model_key=model_key, git_sha=git_sha)
    required_roles = {
        "stage2_semantic_2c_p1",
        "stage2_semantic_2c_p2",
        "stage2_semantic_2c_r1",
        "stage2_semantic_2c_r2",
    }
    observed_roles = {str(record.get("task_role", "")) for record in records}
    if not required_roles.issubset(observed_roles):
        raise ExperimentSafetyError(
            f"accepted {model_key} artifact lacks complete provider request evidence"
        )
    expected_model = EXPECTED_MODELS[model_key]
    for record in records:
        if (
            record.get("requested_model") != expected_model
            or record.get("actual_model") != expected_model
            or record.get("transport") != "deepseek_direct"
            or record.get("fallback_used") is not False
            or record.get("provider_failover_used") is not False
            or record.get("result") != "success"
            or record.get("accounting_status") != "measured"
            or record.get("total_external_cost_usd") is None
        ):
            raise ExperimentSafetyError(
                f"accepted {model_key} provider request evidence is untrusted"
            )
    metrics = _request_metrics(model_key=model_key, git_sha=git_sha)
    if any(row.get(key) != value for key, value in metrics.items()):
        raise ExperimentSafetyError(
            f"accepted {model_key} provider request metrics mismatched"
        )


def _existing_results(
    *, manifest: Mapping[str, Any], git_sha: str
) -> dict[str, Any]:
    if not RESULTS_PATH.is_file():
        return {"model_results": []}
    value = _load_json(RESULTS_PATH, label="existing decomposed Stage 2C results")
    if (
        value.get("experiment_revision") != EXPERIMENT_REVISION
        or value.get("git_sha") != git_sha
        or value.get("manifest_fingerprint") != _manifest_fingerprint(manifest)
    ):
        return {"model_results": []}
    if not isinstance(value.get("model_results"), list):
        raise ExperimentSafetyError("existing decomposed Stage 2C results are malformed")
    rows = value["model_results"]
    if not all(isinstance(row, dict) for row in rows):
        raise ExperimentSafetyError("existing decomposed Stage 2C result row is malformed")
    model_keys = [str(row.get("model_key", "")) for row in rows]
    if (
        any(key not in EXPECTED_MODELS for key in model_keys)
        or len(model_keys) != len(set(model_keys))
    ):
        raise ExperimentSafetyError("existing decomposed Stage 2C result models are invalid")
    return value


def _validate_terminal_result(
    *,
    manifest: Mapping[str, Any],
    git_sha: str,
    row: Mapping[str, Any],
    source_provenance: Mapping[str, Any],
) -> None:
    model_key = str(row.get("model_key", ""))
    if model_key not in EXPECTED_MODELS or row.get("model") != EXPECTED_MODELS[model_key]:
        raise ExperimentSafetyError("terminal Stage 2C result model provenance mismatched")
    for key in (
        "source_checkpoint",
        "source_checkpoint_sha256",
        "source_git_sha",
        "source_stage_1_fingerprints",
        "reused_compiled_stage_2a_fingerprint",
        "reused_compiled_stage_2b_fingerprint",
        "historical_suffix_excluded",
    ):
        if row.get(key) != source_provenance.get(key):
            raise ExperimentSafetyError(
                f"terminal {model_key} Stage 2C result source provenance mismatched"
            )
    status = row.get("status")
    if status == "failed":
        if not isinstance(row.get("failure_code"), str) or not row["failure_code"]:
            raise ExperimentSafetyError(f"terminal {model_key} failure lacks a code")
        return
    if status != "passed_stage_2_stage3_ready":
        raise ExperimentSafetyError(f"terminal {model_key} Stage 2C status is invalid")

    accepted_path = ARTIFACT_ROOT / f"accepted_{model_key}.json"
    accepted = _load_json(accepted_path, label=f"accepted decomposed Stage 2C {model_key} artifact")
    if (
        accepted.get("schema_version") != 1
        or accepted.get("experiment_revision") != EXPERIMENT_REVISION
        or accepted.get("git_sha") != git_sha
        or accepted.get("model_key") != model_key
        or accepted.get("model") != EXPECTED_MODELS[model_key]
        or accepted.get("source_provenance") != source_provenance
    ):
        raise ExperimentSafetyError(f"accepted {model_key} artifact provenance mismatched")
    try:
        artifact = DecomposedStage2CandidateArtifact.model_validate(
            accepted["stage_2_artifact"]
        )
        p1 = Stage2CP1Candidate.model_validate(accepted["stage_2c_p1"])
        p2 = Stage2CP2Candidate.model_validate(accepted["stage_2c_p2"])
        plan = Stage2CPlanCandidate.model_validate(accepted["stage_2c_plan"])
        if assemble_stage2c_plan_candidate(p1, p2) != plan:
            raise ValueError("accepted P1/P2 do not assemble the accepted plan")
    except (KeyError, TypeError, ValueError) as error:
        raise ExperimentSafetyError(f"accepted {model_key} artifact is malformed") from error
    artifact_payload = artifact.model_dump(mode="json")
    artifact_payload.pop("schema_version", None)
    artifact_fingerprint = artifact_payload.pop("artifact_fingerprint", None)
    if artifact_fingerprint != content_fingerprint(artifact_payload):
        raise ExperimentSafetyError(f"accepted {model_key} artifact fingerprint mismatched")
    if (
        row.get("accepted_stage_2_artifact_fingerprint") != artifact.artifact_fingerprint
        or row.get("stage_2c_p1_fingerprint")
        != content_fingerprint(accepted.get("stage_2c_p1"))
        or row.get("stage_2c_p2_fingerprint")
        != content_fingerprint(accepted.get("stage_2c_p2"))
        or row.get("compiled_stage_2c_fingerprint")
        != content_fingerprint(artifact.compiled_stage_2c.model_dump(mode="json"))
        or row.get("stage_2c_plan_fingerprint")
        != content_fingerprint(accepted.get("stage_2c_plan"))
        or row.get("stage_2c_r1_fingerprint")
        != content_fingerprint(accepted.get("stage_2c_r1"))
        or row.get("stage_2c_r2_fingerprint")
        != content_fingerprint(accepted.get("stage_2c_r2"))
        or row.get("reused_compiled_stage_2a_fingerprint")
        != content_fingerprint(artifact.compiled_stage_2a.model_dump(mode="json"))
        or row.get("reused_compiled_stage_2b_fingerprint")
        != content_fingerprint(artifact.compiled_stage_2b.model_dump(mode="json"))
        or not artifact.stage_3_readiness.is_valid
        or len({item.suspect_id for item in artifact.compiled_stage_2c.red_herrings}) != 2
    ):
        raise ExperimentSafetyError(f"accepted {model_key} artifact disposition mismatched")
    checkpoint_records = _load_current_records(
        path=_checkpoint_path(model_key, git_sha),
        manifest=manifest,
        model_key=model_key,
        git_sha=git_sha,
        source_provenance=source_provenance,
    )
    if (
        tuple(str(record.get("stage", "")) for record in checkpoint_records)
        != CURRENT_CHECKPOINT_STAGES
        or accepted.get("accepted_stage_records") != checkpoint_records
    ):
        raise ExperimentSafetyError(f"accepted {model_key} checkpoint is incomplete or mismatched")
    _validate_pass_request_evidence(row=row, model_key=model_key, git_sha=git_sha)


def _terminal_result_may_skip(row: Mapping[str, Any]) -> bool:
    return row.get("status") == "passed_stage_2_stage3_ready"


def _existing_preflights(*, git_sha: str) -> dict[str, dict[str, Any]]:
    if not PREFLIGHTS_PATH.is_file():
        return {}
    value = _load_json(PREFLIGHTS_PATH, label="existing decomposed Stage 2C preflights")
    if value.get("git_sha") != git_sha or not isinstance(value.get("preflights"), list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in value["preflights"]:
        if not isinstance(row, dict) or row.get("model_key") not in EXPECTED_MODELS:
            raise ExperimentSafetyError("existing decomposed Stage 2C preflight is malformed")
        model_key = str(row["model_key"])
        if (
            row.get("requested_model") != EXPECTED_MODELS[model_key]
            or row.get("actual_model") != EXPECTED_MODELS[model_key]
            or row.get("git_sha") != git_sha
            or model_key in result
        ):
            raise ExperimentSafetyError("existing decomposed Stage 2C preflight provenance mismatched")
        result[model_key] = row
    return result


async def _preflight(
    *, api_key: str, model_key: str, git_sha: str, ledger: DeepSeekExperimentLedger
) -> dict[str, Any]:
    observer = DeepSeekRequestObserver(
        ledger=ledger,
        metrics_path=REQUESTS_PATH,
        context=RunContext(
            experiment_revision=EXPERIMENT_REVISION,
            git_sha=git_sha,
            run_id=f"stage2c-plan-items-preflight-{model_key}",
            phase="stage2c_exact_commit_preflight",
            pair_id="Q2C",
            case_fingerprint="preflight",
        ),
        reasoning_by_task_role=_reasoning_map(),
    )
    client = _client(api_key=api_key, model=EXPECTED_MODELS[model_key], observer=observer, reasoning=None)
    response = await client.generate(
        [LLMMessage(role="system", content="Reply with exactly OK."), LLMMessage(role="user", content="OK")],
        max_tokens=8,
        temperature=0.0,
        task_role="stage2c_exact_model_preflight",
    )
    if response.model != EXPECTED_MODELS[model_key] or response.content.strip() != "OK":
        raise ExperimentSafetyError(f"{model_key} exact-model preflight failed")
    return {
        "model_key": model_key,
        "requested_model": EXPECTED_MODELS[model_key],
        "actual_model": response.model,
        "generation_id": response.id,
        "git_sha": git_sha,
        "completed_at": datetime.now(UTC).isoformat(),
    }


async def _run_model(
    *, manifest: Mapping[str, Any], model_key: str, git_sha: str,
    ledger: DeepSeekExperimentLedger, api_key: str,
) -> dict[str, Any]:
    source_records, provenance = verify_historical_prefix(manifest, model_key)
    source_artifact = verify_stage1_artifact(manifest, model_key)
    source_manifest = _load_json(
        Path(__file__).with_name("stage1_semantic_qualification_manifest.json"),
        label="Stage 1 source manifest",
    )
    core = GeneratedCrimeTimelineStage.model_validate(source_artifact["compiled_stage_1"])
    character_ids = tuple(str(value) for value in source_manifest["character_ids"])
    location = load_location(str(source_manifest["location_id"]))
    model = EXPECTED_MODELS[model_key]
    observer = DeepSeekRequestObserver(
        ledger=ledger,
        metrics_path=REQUESTS_PATH,
        context=RunContext(
            experiment_revision=EXPERIMENT_REVISION,
            git_sha=git_sha,
            run_id=f"stage2c-plan-items-{model_key}",
            phase="stage2c_plan_items_qualification",
            pair_id="Q2C",
            case_fingerprint=str(manifest["accepted_stage1"][model_key]["compiled_stage_1_fingerprint"]),
        ),
        reasoning_by_task_role=_reasoning_map(),
    )
    plan_client = _client(api_key=api_key, model=model, observer=observer, reasoning="high")
    realization_client = _client(api_key=api_key, model=model, observer=observer, reasoning=None)
    checkpoint_path = _checkpoint_path(model_key, git_sha)
    current_records = _load_current_records(
        path=checkpoint_path,
        manifest=manifest,
        model_key=model_key,
        git_sha=git_sha,
        source_provenance=provenance,
    )
    diagnostics: list[dict[str, object]] = []
    initial_roles = (
        "stage2_semantic_2c_p1",
        "stage2_semantic_2c_p2",
        "stage2_semantic_2c_r1",
        "stage2_semantic_2c_r2",
    )
    prior_requests = _run_request_records(model_key=model_key, git_sha=git_sha)
    allowed_request_roles = set(_reasoning_map()) - {"stage2c_exact_model_preflight"}
    if any(str(row.get("task_role", "")) not in allowed_request_roles for row in prior_requests):
        raise ExperimentSafetyError(f"{model_key} has an undeclared Stage 2C request role")
    accepted_stage_names = {str(row.get("stage", "")) for row in current_records}
    next_stage_index = next(
        (
            index
            for index, role in enumerate(initial_roles)
            if role not in accepted_stage_names
        ),
        len(initial_roles),
    )
    if (
        "stage2_semantic_2c_p" not in accepted_stage_names
        and any(
            row.get("task_role") in {"stage2_semantic_2c_r1", "stage2_semantic_2c_r2"}
            for row in prior_requests
        )
    ):
        raise ExperimentSafetyError(
            f"{model_key} realization request lacks an assembled plan checkpoint"
        )
    for later_role in initial_roles[next_stage_index + 1 :]:
        if any(row.get("task_role") == later_role for row in prior_requests):
            raise ExperimentSafetyError(f"{model_key} request history skipped a Stage 2C checkpoint")
    consumed_attempts = {
        role: sum(1 for row in prior_requests if row.get("task_role") == role)
        for role in initial_roles
    }
    declared_attempts = int(manifest["limits"]["initial_attempts_per_substage_per_model"])
    remaining_attempts = {
        role: declared_attempts - consumed
        for role, consumed in consumed_attempts.items()
        if role not in accepted_stage_names
    }
    exhausted_role = next(
        (role for role, remaining in remaining_attempts.items() if remaining <= 0),
        None,
    )
    if exhausted_role is not None:
        return {
            "model_key": model_key,
            "model": model,
            "status": "failed",
            "failure_code": "interrupted_attempt_budget_exhausted",
            "exhausted_role": exhausted_role,
            "started_at": datetime.now(UTC).isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "attempt_records": 0,
            **provenance,
            **_request_metrics(model_key=model_key, git_sha=git_sha),
        }

    def record_attempt(record: dict[str, object]) -> None:
        role = str(record.get("stage", ""))
        base_role = role.removesuffix("_syntax_repair").removesuffix("_delta_repair")
        offset = consumed_attempts.get(base_role, 0)
        normalized = dict(record)
        if isinstance(normalized.get("attempt"), int):
            normalized["attempt"] = int(normalized["attempt"]) + offset
        if isinstance(normalized.get("parent_attempt"), int):
            normalized["parent_attempt"] = int(normalized["parent_attempt"]) + offset
        enriched = {
            "schema_version": 1,
            "recorded_at": datetime.now(UTC).isoformat(),
            "experiment_revision": EXPERIMENT_REVISION,
            "git_sha": git_sha,
            "model_key": model_key,
            "model": model,
            **normalized,
        }
        diagnostics.append(enriched)
        _append_jsonl(ATTEMPTS_PATH, enriched)

    def record_accepted(record: dict[str, object]) -> None:
        stage = str(record.get("stage", ""))
        existing = next((row for row in current_records if row.get("stage") == stage), None)
        if existing is not None:
            if existing != record:
                raise ExperimentSafetyError(f"{model_key} accepted checkpoint changed for {stage}")
            return
        if len(current_records) >= len(CURRENT_CHECKPOINT_STAGES) or stage != CURRENT_CHECKPOINT_STAGES[len(current_records)]:
            raise ExperimentSafetyError(f"{model_key} accepted checkpoint arrived out of order")
        current_records.append(record)
        _atomic_json(
            checkpoint_path,
            {
                "schema_version": 1,
                "experiment_revision": EXPERIMENT_REVISION,
                "manifest_fingerprint": _manifest_fingerprint(manifest),
                "branch": EXPECTED_BRANCH,
                "git_sha": git_sha,
                "model_key": model_key,
                "model": model,
                "prompt_revision": STAGE2C_PLAN_ITEMS_PROMPT_REVISION,
                "schema_revision": STAGE2C_PLAN_ITEMS_SCHEMA_REVISION,
                "source_stage2_git_sha": manifest["source_stage2"]["git_sha"],
                "source_stage2_manifest_fingerprint": manifest["source_stage2"]["manifest_fingerprint"],
                "source_stage1_fingerprints": manifest["accepted_stage1"][model_key],
                "source_stage2_fingerprints": manifest["source_stage2"]["accepted_compiled_stage2"][model_key],
                "source_checkpoint_sha256": provenance["source_checkpoint_sha256"],
                "updated_at": datetime.now(UTC).isoformat(),
                "accepted_stage_records": current_records,
            },
        )

    started_at = datetime.now(UTC).isoformat()
    resume_records = {
        str(row["stage"]): row for row in (*source_records, *current_records)
        if row.get("stage") != "stage2_assembled_stage3_ready"
    }
    try:
        boundary = await generate_stage2_boundary(
            plan_client,
            repair_llm=realization_client,
            stage2c_realization_llm=realization_client,
            decomposed_stage2c=True,
            decomposed_stage2c_plan_items=True,
            core=core,
            character_ids=character_ids,
            location=location,
            max_initial_attempts=int(manifest["limits"]["initial_attempts_per_substage_per_model"]),
            max_delta_repairs=int(manifest["limits"]["delta_repairs_per_parsed_candidate"]),
            initial_attempts_by_role={
                role: remaining
                for role, remaining in remaining_attempts.items()
                if remaining > 0
            },
            attempt_observer=record_attempt,
            accepted_stage_observer=record_accepted,
            resume_stage_records=resume_records,
        )
    except Stage2SemanticError as error:
        if error.code == "experiment_safety_stop":
            raise ExperimentSafetyError("qualification stopped at a request or accounting safety gate") from error
        return {
            "model_key": model_key,
            "model": model,
            "status": "failed",
            "failure_code": error.code,
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "attempt_records": len(diagnostics),
            **provenance,
            **_request_metrics(model_key=model_key, git_sha=git_sha),
        }
    request_metrics = _request_metrics(model_key=model_key, git_sha=git_sha)
    request_roles = set(request_metrics["request_roles"])
    if any("stage3" in role or "overlay" in role for role in request_roles):
        raise ExperimentSafetyError("Stage 3 provider activity crossed the stop boundary")
    accepted_by_stage = {
        str(record["stage"]): record for record in current_records
    }
    p1_document = accepted_by_stage["stage2_semantic_2c_p1"][
        "model_authored_document"
    ]
    p2_document = accepted_by_stage["stage2_semantic_2c_p2"][
        "model_authored_document"
    ]
    private_document = {
        "schema_version": 1,
        "experiment_revision": EXPERIMENT_REVISION,
        "git_sha": git_sha,
        "model_key": model_key,
        "model": model,
        "source_provenance": provenance,
        "stage_2c_p1": p1_document,
        "stage_2c_p2": p2_document,
        "stage_2c_plan": boundary.stage_2c_plan.model_dump(mode="json"),
        "stage_2c_r1": boundary.stage_2c_r1.model_dump(mode="json"),
        "stage_2c_r2": boundary.stage_2c_r2.model_dump(mode="json"),
        "stage_2c_semantic_candidate": boundary.stage_2c_candidate.model_dump(mode="json"),
        "stage_2_artifact": boundary.artifact.model_dump(mode="json"),
        "accepted_stage_records": current_records,
    }
    _atomic_json(ARTIFACT_ROOT / f"accepted_{model_key}.json", private_document)
    return {
        "model_key": model_key,
        "model": model,
        "status": "passed_stage_2_stage3_ready",
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        **provenance,
        "stage_2c_p1_fingerprint": content_fingerprint(p1_document),
        "stage_2c_p2_fingerprint": content_fingerprint(p2_document),
        "stage_2c_plan_fingerprint": content_fingerprint(boundary.stage_2c_plan.model_dump(mode="json")),
        "stage_2c_r1_fingerprint": content_fingerprint(boundary.stage_2c_r1.model_dump(mode="json")),
        "stage_2c_r2_fingerprint": content_fingerprint(boundary.stage_2c_r2.model_dump(mode="json")),
        "compiled_stage_2c_fingerprint": content_fingerprint(boundary.artifact.compiled_stage_2c.model_dump(mode="json")),
        "accepted_stage_2_artifact_fingerprint": boundary.artifact.artifact_fingerprint,
        "red_herrings": len(boundary.artifact.compiled_stage_2c.red_herrings),
        "distinct_red_herring_suspects": len({row.suspect_id for row in boundary.artifact.compiled_stage_2c.red_herrings}),
        "stage_3_readiness": boundary.artifact.stage_3_readiness.is_valid,
        "attempt_records": len(diagnostics),
        **request_metrics,
    }


async def run_paid_qualification(manifest: Mapping[str, Any]) -> dict[str, Any]:
    branch, git_sha = qualification_git_identity(require_clean=True)
    verify_revision15_baseline(manifest)
    verified = {key: verify_historical_prefix(manifest, key)[1] for key in manifest["model_order"]}
    historical_flash = REPOSITORY_ROOT / str(manifest["historical_flash_artifact"])
    historical_flash_sha256 = _file_fingerprint(historical_flash)
    ledger = DeepSeekExperimentLedger(LEDGER_PATH, policy=_budget_policy(manifest))
    if ledger.snapshot()["open_reservations"]:
        raise ExperimentSafetyError("decomposed Stage 2C ledger has unresolved reservations")
    api_key = load_direct_api_key()
    existing = _existing_results(manifest=manifest, git_sha=git_sha)
    for row in existing.get("model_results", []):
        _validate_terminal_result(
            manifest=manifest,
            git_sha=git_sha,
            row=row,
            source_provenance=verified[str(row["model_key"])],
        )
    existing_by_model = {
        str(row["model_key"]): row
        for row in existing.get("model_results", [])
        if isinstance(row, dict) and row.get("model_key") in EXPECTED_MODELS
    }
    existing_preflights = _existing_preflights(git_sha=git_sha)
    plan = {
        "schema_version": 1,
        "experiment_revision": EXPERIMENT_REVISION,
        "status": "running",
        "created_at": existing.get("created_at", datetime.now(UTC).isoformat()),
        "branch": branch,
        "git_sha": git_sha,
        "manifest_fingerprint": _manifest_fingerprint(manifest),
        "verified_source_provenance": verified,
        "historical_flash_artifact_sha256": historical_flash_sha256,
        "stop_boundary": manifest["stop_boundary"],
    }
    _atomic_json(PLAN_PATH, plan)
    preflights: list[dict[str, Any]] = [
        existing_preflights[key]
        for key in manifest["model_order"]
        if key in existing_preflights
    ]
    results: list[dict[str, Any]] = []
    for model_key in manifest["model_order"]:
        prior = existing_by_model.get(str(model_key))
        if isinstance(prior, dict) and _terminal_result_may_skip(prior):
            results.append(prior)
            continue
        if model_key not in existing_preflights:
            preflight = await _preflight(
                api_key=api_key,
                model_key=str(model_key),
                git_sha=git_sha,
                ledger=ledger,
            )
            existing_preflights[str(model_key)] = preflight
            preflights = [
                existing_preflights[key]
                for key in manifest["model_order"]
                if key in existing_preflights
            ]
            _atomic_json(
                PREFLIGHTS_PATH,
                {"schema_version": 1, "git_sha": git_sha, "preflights": preflights},
            )
        results.append(
            await _run_model(
                manifest=manifest,
                model_key=str(model_key),
                git_sha=git_sha,
                ledger=ledger,
                api_key=api_key,
            )
        )
        _atomic_json(
            RESULTS_PATH,
            {
                "schema_version": 1,
                "experiment_revision": EXPERIMENT_REVISION,
                "status": "running",
                "created_at": plan["created_at"],
                "branch": branch,
                "git_sha": git_sha,
                "manifest_fingerprint": _manifest_fingerprint(manifest),
                "model_results": results,
                "budget": _json_ready(ledger.snapshot()),
                "stage_3_requests": 0,
            },
        )
    passed = {row["model_key"] for row in results if row.get("status") == "passed_stage_2_stage3_ready"}
    status = "completed" if passed == {"flash", "pro"} else "completed_with_failures"
    carry = Decimal(str(manifest["budget"]["carry_in_stage2_cost_usd"]))
    snapshot = ledger.snapshot()
    final = {
        "schema_version": 1,
        "experiment_revision": EXPERIMENT_REVISION,
        "status": status,
        "created_at": plan["created_at"],
        "completed_at": datetime.now(UTC).isoformat(),
        "branch": branch,
        "git_sha": git_sha,
        "manifest_fingerprint": _manifest_fingerprint(manifest),
        "model_results": results,
        "budget": _json_ready(snapshot),
        "cumulative_stage2_estimated_cost_usd": format(carry + Decimal(str(snapshot["settled_usd"])), "f"),
        "historical_flash_artifact_sha256": historical_flash_sha256,
        "stage_3_requests": 0,
    }
    _atomic_json(RESULTS_PATH, final)
    plan["status"] = status
    plan["completed_at"] = final["completed_at"]
    _atomic_json(PLAN_PATH, plan)
    return final


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Run paid direct-DeepSeek Stage 2C qualification")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = load_manifest()
    validate_manifest(manifest)
    revision15 = verify_revision15_baseline(manifest)
    verified = {key: verify_historical_prefix(manifest, key)[1] for key in manifest["model_order"]}
    branch, git_sha = qualification_git_identity(require_clean=args.execute)
    if not args.execute:
        print(json.dumps({
            "status": "ready",
            "branch": branch,
            "git_sha": git_sha,
            "manifest": str(MANIFEST_PATH.relative_to(REPOSITORY_ROOT)),
            "verified_source_provenance": verified,
            "revision15_results_sha256": manifest["source_stage2c_revision15"]["results_sha256"],
            "revision15_status": revision15["status"],
            "policy_fingerprint": content_fingerprint(QUALIFICATION_POLICY.model_dump(mode="json")),
            "paid_calls_made": 0,
        }, indent=2, sort_keys=True))
        return 0
    result = asyncio.run(run_paid_qualification(manifest))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
