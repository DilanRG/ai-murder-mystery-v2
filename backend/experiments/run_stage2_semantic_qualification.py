"""Bounded direct-DeepSeek qualification of the semantic Stage 2 boundary."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from experiments.deepseek_v4_runtime import (
    DeepSeekRequestObserver,
    RunContext,
    load_direct_api_key,
)
from experiments.deepseek_v4_runner import ExperimentSafetyError
from game.case_generation import (
    GeneratedCrimeTimelineStage,
    ProofSupportCatalog,
    proof_support_catalog_fingerprint,
)
from game.content import load_location
from game.stage1_semantic import content_fingerprint
from game.stage2_semantic import (
    QUALIFICATION_POLICY,
    STAGE2A_MAX_TOKENS,
    STAGE2B_MAX_TOKENS,
    STAGE2C_MAX_TOKENS,
    STAGE2_DELTA_REPAIR_MAX_TOKENS,
    STAGE2_PROMPT_REVISION,
    STAGE2_SCHEMA_REVISION,
    STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
    Stage2SemanticError,
    generate_stage2_boundary,
)
from llm.client import LLMClient, LLMMessage, LLMProviderError
from llm.experiment import (
    BudgetStop,
    DeepSeekExperimentLedger,
    ExperimentPolicy,
    ExperimentPolicyError,
    LedgerIntegrityError,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
MANIFEST_PATH = Path(__file__).with_name("stage2_semantic_qualification_manifest.json")
SOURCE_ROOT = REPOSITORY_ROOT / ".private" / "stage1_semantic_qualification"
SOURCE_MANIFEST_PATH = Path(__file__).with_name("stage1_semantic_qualification_manifest.json")
ARTIFACT_ROOT = REPOSITORY_ROOT / ".private" / "stage2_semantic_qualification"
ATTEMPTS_PATH = ARTIFACT_ROOT / "attempts.jsonl"
REQUESTS_PATH = ARTIFACT_ROOT / "requests.jsonl"
LEDGER_PATH = ARTIFACT_ROOT / "cost_ledger.jsonl"
PLAN_PATH = ARTIFACT_ROOT / "qualification_plan.json"
RESULTS_PATH = ARTIFACT_ROOT / "qualification_results.json"
PREFLIGHTS_PATH = ARTIFACT_ROOT / "verified_preflights.json"
EXPECTED_BRANCH = "stage2-semantic-compiler"
EXPECTED_MODELS = {
    "flash": "deepseek-v4-flash",
    "pro": "deepseek-v4-pro",
}


class Stage2ProviderPolicy(ExperimentPolicy):
    """Fresh Stage 2 ledger allowing high-reasoning generation and no-think repair."""

    def validate_request(
        self,
        *,
        provider: str,
        model: str,
        allow_fallbacks: bool,
        parameters: Mapping[str, Any] | None,
        reasoning: str,
    ) -> None:
        super().validate_request(
            provider=provider,
            model=model,
            allow_fallbacks=allow_fallbacks,
            parameters=parameters,
            reasoning="high",
        )
        if reasoning not in {"high", "none"}:
            raise ExperimentPolicyError(
                "Stage 2 reasoning must be high or explicitly disabled"
            )


def _atomic_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with path.open("ab") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentSafetyError(f"{label} is unavailable or malformed") from error
    if not isinstance(value, dict):
        raise ExperimentSafetyError(f"{label} must be a JSON object")
    return value


def load_manifest() -> dict[str, Any]:
    return _load_json(MANIFEST_PATH, label="Stage 2 qualification manifest")


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != 1 or manifest.get("experiment_revision") != 12:
        raise ExperimentSafetyError("Unexpected Stage 2 qualification revision")
    if manifest.get("branch") != EXPECTED_BRANCH:
        raise ExperimentSafetyError("Stage 2 qualification branch changed")
    if manifest.get("baseline_sha") != "f87d267033b5069966b36fa632869e1a8f3379c6":
        raise ExperimentSafetyError("Stage 2 baseline changed")
    if manifest.get("stage1_qualification_code_sha") != "bbf7d1f46cfc138f442c298e0a57ead0a7bacab4":
        raise ExperimentSafetyError("Stage 1 qualification provenance changed")
    if manifest.get("prompt_revision") != STAGE2_PROMPT_REVISION:
        raise ExperimentSafetyError("Stage 2 prompt revision differs from code")
    if manifest.get("schema_revision") != STAGE2_SCHEMA_REVISION:
        raise ExperimentSafetyError("Stage 2 schema revision differs from code")
    if manifest.get("transport") != "deepseek_direct" or manifest.get("provider_fallbacks") is not False:
        raise ExperimentSafetyError("Stage 2 qualification must use direct DeepSeek without fallback")
    if manifest.get("model_order") != ["flash", "pro"] or manifest.get("models") != EXPECTED_MODELS:
        raise ExperimentSafetyError("Stage 2 model order or exact slugs changed")
    if manifest.get("policy") != {
        "true_routes": 2,
        "primary_roles_per_route": 3,
        "true_evidence_roles": 6,
        "red_herrings": 2,
        "minimum_non_voluntary_routes": 1,
        "unique_responsible_actor": True,
    }:
        raise ExperimentSafetyError("Stage 2 fixed qualification policy changed")
    if manifest.get("limits") != {
        "initial_attempts_per_substage_per_model": 3,
        "delta_repairs_per_parsed_candidate": 2,
        "stage_2a_max_tokens": STAGE2A_MAX_TOKENS,
        "stage_2b_max_tokens": STAGE2B_MAX_TOKENS,
        "stage_2c_max_tokens": STAGE2C_MAX_TOKENS,
        "syntax_repair_max_tokens": STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
        "delta_repair_max_tokens": STAGE2_DELTA_REPAIR_MAX_TOKENS,
    }:
        raise ExperimentSafetyError("Stage 2 attempt or output limits changed")
    if manifest.get("reasoning") != {
        "semantic_initial": "high",
        "syntax_repair": "disabled",
        "delta_repair": "disabled",
    }:
        raise ExperimentSafetyError("Stage 2 reasoning policy changed")
    if manifest.get("budget") != {
        "namespace": "stage2_semantic_qualification",
        "fresh_budget_usd": "10.00",
        "soft_stop_usd": "8.50",
        "hard_stop_usd": "9.50",
        "uncertainty_reserve_usd": "0.50",
    }:
        raise ExperimentSafetyError("Stage 2 budget policy changed")
    if manifest.get("stop_boundary") != "stage3_private_overlays":
        raise ExperimentSafetyError("Stage 2 stop boundary changed")
    expected_inputs = {
        "flash": {
            "semantic_plan_fingerprint": "5428e613bfbbaed4c149843f913d5007a3e59914c02a65de034fb3ae186dbbf4",
            "compiled_stage_1_fingerprint": "f3dfdf8eb50f06c5ff5dc267141f2aaf2ca8b50c92f02ad5ddec7ec659c11166",
            "proof_support_catalogue_fingerprint": "2727a28b41880a54ff0a1b93b96fc04f08c4d7da0cd9af2bce569ab8bfc7a85c",
        },
        "pro": {
            "semantic_plan_fingerprint": "87d90da4b06ad0eea1b2cc987445134e6eb241c6ea6d91bb4fe779395ab66814",
            "compiled_stage_1_fingerprint": "642f86e0ffd8a60a5ee372727ecdb6788432765df45dac74d46e2ea0334b26fd",
            "proof_support_catalogue_fingerprint": "d3ed314b09e9769b7af26ee5f85dd017257b99f18b4a586f0e605557630081da",
        },
    }
    if manifest.get("accepted_stage1") != expected_inputs:
        raise ExperimentSafetyError("Accepted Stage 1 fingerprints changed")


def verify_stage1_artifact(
    manifest: Mapping[str, Any],
    model_key: str,
) -> dict[str, Any]:
    path = SOURCE_ROOT / f"accepted_{model_key}.json"
    artifact = _load_json(path, label=f"accepted private Stage 1 {model_key} artifact")
    if artifact.get("git_sha") != manifest["stage1_qualification_code_sha"]:
        raise ExperimentSafetyError(f"{model_key} Stage 1 code provenance mismatched")
    if artifact.get("model") != EXPECTED_MODELS[model_key]:
        raise ExperimentSafetyError(f"{model_key} Stage 1 model provenance mismatched")
    expected = manifest["accepted_stage1"][model_key]
    actual = {
        "semantic_plan_fingerprint": content_fingerprint(artifact.get("semantic_plan")),
        "compiled_stage_1_fingerprint": content_fingerprint(artifact.get("compiled_stage_1")),
        "proof_support_catalogue_fingerprint": proof_support_catalog_fingerprint(
            ProofSupportCatalog.model_validate(artifact.get("proof_support_catalog"))
        ),
    }
    if actual != expected:
        raise ExperimentSafetyError(f"{model_key} private Stage 1 fingerprint mismatched")
    return artifact


def _git_output(*args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return process.stdout.strip()


def qualification_git_identity(*, require_clean: bool) -> tuple[str, str]:
    branch = _git_output("rev-parse", "--abbrev-ref", "HEAD")
    sha = _git_output("rev-parse", "HEAD")
    if branch != EXPECTED_BRANCH:
        raise ExperimentSafetyError("Stage 2 qualification is running from the wrong branch")
    if require_clean and _git_output("status", "--porcelain=v1"):
        raise ExperimentSafetyError("Paid Stage 2 qualification requires a clean exact commit")
    return branch, sha


def _safe_callback(observer: DeepSeekRequestObserver):
    async def callback(event: str, data: dict[str, Any]) -> None:
        try:
            await observer(event, data)
        except (
            ExperimentSafetyError,
            BudgetStop,
            ExperimentPolicyError,
            LedgerIntegrityError,
        ) as error:
            raise LLMProviderError(
                "Stage 2 qualification safety gate stopped execution",
                code="experiment_safety_stop",
                retryable=False,
            ) from error

    return callback


def _client(
    *,
    api_key: str,
    model: str,
    observer: DeepSeekRequestObserver,
    reasoning: str | None,
) -> LLMClient:
    if reasoning is None:
        task_limits = {
            "stage2_semantic_2a_syntax_repair": STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
            "stage2_semantic_2b_syntax_repair": STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
            "stage2_semantic_2c_syntax_repair": STAGE2_SYNTAX_REPAIR_MAX_TOKENS,
            "stage2_semantic_2a_delta_repair": STAGE2_DELTA_REPAIR_MAX_TOKENS,
            "stage2_semantic_2b_delta_repair": STAGE2_DELTA_REPAIR_MAX_TOKENS,
            "stage2_semantic_2c_delta_repair": STAGE2_DELTA_REPAIR_MAX_TOKENS,
            "stage2_exact_model_preflight": 8,
        }
        max_tokens = STAGE2_SYNTAX_REPAIR_MAX_TOKENS
    else:
        task_limits = {
            "stage2_semantic_2a": STAGE2A_MAX_TOKENS,
            "stage2_semantic_2b": STAGE2B_MAX_TOKENS,
            "stage2_semantic_2c": STAGE2C_MAX_TOKENS,
        }
        max_tokens = STAGE2B_MAX_TOKENS
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
        task_max_tokens=task_limits,
    )


def _reasoning_map() -> dict[str, str | None]:
    result: dict[str, str | None] = {
        "stage2_semantic_2a": "high",
        "stage2_semantic_2b": "high",
        "stage2_semantic_2c": "high",
        "stage2_exact_model_preflight": None,
    }
    for stage in ("stage2_semantic_2a", "stage2_semantic_2b", "stage2_semantic_2c"):
        result[f"{stage}_syntax_repair"] = None
        result[f"{stage}_delta_repair"] = None
    return result


def _json_ready(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


async def _preflight(
    *,
    api_key: str,
    model_key: str,
    git_sha: str,
    ledger: DeepSeekExperimentLedger,
    stage1_fingerprint: str,
) -> dict[str, Any]:
    observer = DeepSeekRequestObserver(
        ledger=ledger,
        metrics_path=REQUESTS_PATH,
        context=RunContext(
            experiment_revision=12,
            git_sha=git_sha,
            run_id=f"stage2-preflight-{model_key}",
            phase="stage2_exact_commit_preflight",
            pair_id="Q2",
            case_fingerprint=stage1_fingerprint,
        ),
        reasoning_by_task_role=_reasoning_map(),
    )
    client = _client(
        api_key=api_key,
        model=EXPECTED_MODELS[model_key],
        observer=observer,
        reasoning=None,
    )
    response = await client.generate(
        [
            LLMMessage(role="system", content="Reply with exactly OK."),
            LLMMessage(role="user", content="OK"),
        ],
        max_tokens=8,
        temperature=0.0,
        task_role="stage2_exact_model_preflight",
    )
    if response.model != EXPECTED_MODELS[model_key] or response.content.strip() != "OK":
        raise ExperimentSafetyError(f"{model_key} exact-model preflight failed")
    return {
        "model_key": model_key,
        "requested_model": EXPECTED_MODELS[model_key],
        "actual_model": response.model,
        "generation_id": response.id,
        "git_sha": git_sha,
        "content_ok": True,
        "completed_at": datetime.now(UTC).isoformat(),
    }


async def _run_model(
    *,
    manifest: Mapping[str, Any],
    model_key: str,
    source_artifact: Mapping[str, Any],
    git_sha: str,
    ledger: DeepSeekExperimentLedger,
    api_key: str,
) -> dict[str, Any]:
    model = EXPECTED_MODELS[model_key]
    source_manifest = _load_json(SOURCE_MANIFEST_PATH, label="Stage 1 source manifest")
    character_ids = tuple(str(value) for value in source_manifest["character_ids"])
    location = load_location(str(source_manifest["location_id"]))
    core = GeneratedCrimeTimelineStage.model_validate(source_artifact["compiled_stage_1"])
    observer = DeepSeekRequestObserver(
        ledger=ledger,
        metrics_path=REQUESTS_PATH,
        context=RunContext(
            experiment_revision=12,
            git_sha=git_sha,
            run_id=f"stage2-semantic-{model_key}",
            phase="stage2_qualification",
            pair_id="Q2",
            case_fingerprint=str(source_artifact["compiled_stage_1_fingerprint"]),
        ),
        reasoning_by_task_role=_reasoning_map(),
    )
    initial_client = _client(
        api_key=api_key,
        model=model,
        observer=observer,
        reasoning="high",
    )
    repair_client = _client(
        api_key=api_key,
        model=model,
        observer=observer,
        reasoning=None,
    )
    diagnostics: list[dict[str, object]] = []

    def record_attempt(record: dict[str, object]) -> None:
        enriched = {
            "schema_version": 1,
            "recorded_at": datetime.now(UTC).isoformat(),
            "experiment_revision": 12,
            "git_sha": git_sha,
            "model_key": model_key,
            "model": model,
            **record,
        }
        diagnostics.append(enriched)
        _append_jsonl(ATTEMPTS_PATH, enriched)

    accepted_stages: list[dict[str, object]] = []

    def record_accepted(record: dict[str, object]) -> None:
        accepted_stages.append(record)

    started_at = datetime.now(UTC).isoformat()
    try:
        boundary = await generate_stage2_boundary(
            initial_client,
            repair_llm=repair_client,
            core=core,
            character_ids=character_ids,
            location=location,
            max_initial_attempts=int(manifest["limits"]["initial_attempts_per_substage_per_model"]),
            max_delta_repairs=int(manifest["limits"]["delta_repairs_per_parsed_candidate"]),
            attempt_observer=record_attempt,
            accepted_stage_observer=record_accepted,
        )
    except Stage2SemanticError as error:
        if error.code == "experiment_safety_stop":
            raise ExperimentSafetyError(
                "Stage 2 qualification stopped at an accounting or request safety gate"
            ) from error
        return {
            "model_key": model_key,
            "model": model,
            "status": "failed",
            "failure_code": error.code,
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "attempt_records": len(diagnostics),
            "request_records": len(observer.records),
            "locally_estimated_cost_usd": format(
                sum(
                    (Decimal(str(record.get("total_external_cost_usd", 0))) for record in observer.records),
                    Decimal("0"),
                ),
                "f",
            ),
        }
    if any(str(record.get("stage", "")).startswith("stage3") for record in accepted_stages):
        raise ExperimentSafetyError("Stage 3 activity crossed the declared stop boundary")
    private_document = {
        "schema_version": 1,
        "experiment_revision": 12,
        "git_sha": git_sha,
        "model_key": model_key,
        "model": model,
        "input_stage_1_fingerprints": manifest["accepted_stage1"][model_key],
        "proof_support_catalogue": boundary.support_catalogue.model_dump(mode="json"),
        "discovery_affordance_catalogue": boundary.discovery_catalogue.model_dump(mode="json"),
        "secondary_secret_catalogue": boundary.secondary_secret_catalogue.model_dump(mode="json"),
        "stage_2a_semantic_candidate": boundary.stage_2a_candidate.model_dump(mode="json"),
        "compiled_stage_2a": boundary.compiled_stage_2a.model_dump(mode="json"),
        "stage_2b_semantic_candidate": boundary.stage_2b_candidate.model_dump(mode="json"),
        "compiled_stage_2b": boundary.compiled_stage_2b.model_dump(mode="json"),
        "stage_2c_semantic_candidate": boundary.stage_2c_candidate.model_dump(mode="json"),
        "stage_2_artifact": boundary.artifact.model_dump(mode="json"),
        "accepted_stage_records": accepted_stages,
    }
    _atomic_json(ARTIFACT_ROOT / f"accepted_{model_key}.json", private_document)
    return {
        "model_key": model_key,
        "model": model,
        "status": "passed_stage_2_stage3_ready",
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "input_compiled_stage_1_fingerprint": manifest["accepted_stage1"][model_key]["compiled_stage_1_fingerprint"],
        "proof_support_catalogue_fingerprint": boundary.artifact.proof_support_catalogue_fingerprint,
        "discovery_affordance_catalogue_fingerprint": boundary.artifact.discovery_affordance_catalogue_fingerprint,
        "compiled_stage_2a_fingerprint": content_fingerprint(boundary.compiled_stage_2a.model_dump(mode="json")),
        "compiled_stage_2b_fingerprint": content_fingerprint(boundary.compiled_stage_2b.model_dump(mode="json")),
        "compiled_stage_2c_fingerprint": content_fingerprint(boundary.compiled_stage_2c.model_dump(mode="json")),
        "accepted_stage_2_artifact_fingerprint": boundary.artifact.artifact_fingerprint,
        "true_routes": len(boundary.compiled_stage_2a.routes),
        "true_evidence_roles": len(boundary.compiled_stage_2b.evidence),
        "red_herrings": len(boundary.compiled_stage_2c.red_herrings),
        "fully_non_voluntary_routes": len(boundary.compiled_stage_2b.fully_non_voluntary_route_ids),
        "deferred_stage_3_obligations": len(
            boundary.artifact.stage_3_readiness.deferred_stage_3_obligations
        ),
        "attempt_records": len(diagnostics),
        "request_records": len(observer.records),
        "locally_estimated_cost_usd": format(
            sum(
                (Decimal(str(record.get("total_external_cost_usd", 0))) for record in observer.records),
                Decimal("0"),
            ),
            "f",
        ),
    }


def _existing_results() -> dict[str, Any]:
    if not RESULTS_PATH.is_file():
        return {"schema_version": 1, "status": "running", "model_results": []}
    value = _load_json(RESULTS_PATH, label="existing Stage 2 qualification results")
    if not isinstance(value.get("model_results"), list):
        raise ExperimentSafetyError("Existing Stage 2 results are malformed")
    return value


async def run_paid_qualification(manifest: Mapping[str, Any]) -> dict[str, Any]:
    branch, git_sha = qualification_git_identity(require_clean=True)
    sources = {
        model_key: verify_stage1_artifact(manifest, model_key)
        for model_key in manifest["model_order"]
    }
    ledger = DeepSeekExperimentLedger(LEDGER_PATH, policy=Stage2ProviderPolicy())
    if ledger.snapshot()["open_reservations"]:
        raise ExperimentSafetyError(
            "Stage 2 ledger has an unresolved reservation; accounting is not trustworthy"
        )
    existing = _existing_results()
    existing_by_model = {
        item["model_key"]: item
        for item in existing["model_results"]
        if isinstance(item, dict) and item.get("model_key") in EXPECTED_MODELS
    }
    plan = {
        "schema_version": 1,
        "status": "running",
        "created_at": existing.get("created_at", datetime.now(UTC).isoformat()),
        "updated_at": datetime.now(UTC).isoformat(),
        "branch": branch,
        "git_sha": git_sha,
        "manifest_fingerprint": hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "model_order": manifest["model_order"],
        "stop_boundary": manifest["stop_boundary"],
    }
    _atomic_json(PLAN_PATH, plan)
    api_key = load_direct_api_key()
    preflights = []
    model_results: list[dict[str, Any]] = []
    for model_key in manifest["model_order"]:
        prior = existing_by_model.get(model_key)
        if isinstance(prior, dict) and prior.get("status") in {
            "passed_stage_2_stage3_ready",
            "failed",
        }:
            model_results.append(prior)
            continue
        preflight = await _preflight(
            api_key=api_key,
            model_key=str(model_key),
            git_sha=git_sha,
            ledger=ledger,
            stage1_fingerprint=str(
                manifest["accepted_stage1"][model_key]["compiled_stage_1_fingerprint"]
            ),
        )
        preflights.append(preflight)
        _atomic_json(
            PREFLIGHTS_PATH,
            {
                "schema_version": 1,
                "git_sha": git_sha,
                "preflights": preflights,
            },
        )
        result = await _run_model(
            manifest=manifest,
            model_key=str(model_key),
            source_artifact=sources[model_key],
            git_sha=git_sha,
            ledger=ledger,
            api_key=api_key,
        )
        model_results.append(result)
        _atomic_json(
            RESULTS_PATH,
            {
                "schema_version": 1,
                "status": "running",
                "created_at": plan["created_at"],
                "updated_at": datetime.now(UTC).isoformat(),
                "branch": branch,
                "git_sha": git_sha,
                "model_results": model_results,
                "budget": _json_ready(ledger.snapshot()),
                "stage_3_requests": 0,
            },
        )
    passed = {
        item["model_key"]
        for item in model_results
        if item.get("status") == "passed_stage_2_stage3_ready"
    }
    status = "completed" if passed == {"flash", "pro"} else "completed_with_failures"
    results = {
        "schema_version": 1,
        "status": status,
        "created_at": plan["created_at"],
        "completed_at": datetime.now(UTC).isoformat(),
        "branch": branch,
        "git_sha": git_sha,
        "model_results": model_results,
        "budget": _json_ready(ledger.snapshot()),
        "stage_3_requests": 0,
    }
    _atomic_json(RESULTS_PATH, results)
    plan["status"] = status
    plan["updated_at"] = results["completed_at"]
    _atomic_json(PLAN_PATH, plan)
    return results


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Run paid direct-DeepSeek qualification")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = load_manifest()
    validate_manifest(manifest)
    sources = {
        model_key: verify_stage1_artifact(manifest, model_key)
        for model_key in manifest["model_order"]
    }
    branch, sha = qualification_git_identity(require_clean=args.execute)
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "ready",
                    "branch": branch,
                    "git_sha": sha,
                    "manifest": str(MANIFEST_PATH.relative_to(REPOSITORY_ROOT)),
                    "verified_stage1_models": sorted(sources),
                    "policy_fingerprint": content_fingerprint(
                        QUALIFICATION_POLICY.model_dump(mode="json")
                    ),
                    "model_order": manifest["model_order"],
                    "paid_calls_made": 0,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    results = asyncio.run(run_paid_qualification(manifest))
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if results["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
