"""Bounded direct-DeepSeek qualification for the semantic Stage 1 boundary."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
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
    _validate_core_stage,
    build_proof_support_catalog,
    proof_support_catalog_fingerprint,
)
from game.content import load_location
from game.stage1_semantic import (
    STAGE1_PLAN_MAX_TOKENS,
    STAGE1_PROMPT_REVISION,
    STAGE1_REPAIR_MAX_TOKENS,
    STAGE1_SCHEMA_REVISION,
    STAGE1_SYNTAX_REPAIR_MAX_TOKENS,
    Stage1SemanticError,
    generate_stage1_boundary,
    role_assignment_fingerprint,
    select_stage1_roles,
)
from llm.client import LLMClient, LLMProviderError
from llm.experiment import (
    BudgetStop,
    DeepSeekExperimentLedger,
    ExperimentPolicy,
    ExperimentPolicyError,
    LedgerIntegrityError,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
MANIFEST_PATH = Path(__file__).with_name("stage1_semantic_qualification_manifest.json")
ARTIFACT_ROOT = REPOSITORY_ROOT / ".private" / "stage1_semantic_qualification"
ATTEMPTS_PATH = ARTIFACT_ROOT / "attempts.jsonl"
REQUESTS_PATH = ARTIFACT_ROOT / "requests.jsonl"
LEDGER_PATH = ARTIFACT_ROOT / "cost_ledger.jsonl"
PLAN_PATH = ARTIFACT_ROOT / "qualification_plan.json"
RESULTS_PATH = ARTIFACT_ROOT / "qualification_results.json"
EXPECTED_BRANCH = "stage1-semantic-compiler"
EXPECTED_MODELS = {
    "flash": "deepseek-v4-flash",
    "pro": "deepseek-v4-pro",
}


class Stage1QualificationPolicy(ExperimentPolicy):
    """Fresh budget policy allowing high-reasoning plans and bounded no-think repair."""

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
                "Stage 1 qualification reasoning must be high or explicitly disabled"
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


def _load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentSafetyError("Stage 1 qualification manifest is unavailable") from error
    if not isinstance(value, dict):
        raise ExperimentSafetyError("Stage 1 qualification manifest must be an object")
    return value


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != 1 or manifest.get("experiment_revision") != 11:
        raise ExperimentSafetyError("Unexpected Stage 1 qualification revision")
    if manifest.get("prompt_revision") != STAGE1_PROMPT_REVISION:
        raise ExperimentSafetyError("Manifest prompt revision differs from code")
    if manifest.get("schema_revision") != STAGE1_SCHEMA_REVISION:
        raise ExperimentSafetyError("Manifest schema revision differs from code")
    if manifest.get("transport") != "deepseek_direct" or manifest.get("provider_fallbacks") is not False:
        raise ExperimentSafetyError("Qualification must use direct DeepSeek without fallback")
    if manifest.get("baseline_sha") != "682d4f38c3d2e6f674f6e22f26deb661f14b69c7":
        raise ExperimentSafetyError("Qualification baseline changed")
    if (
        manifest.get("location_id") != "ashwick_manor"
        or manifest.get("death_mode") != "homicide"
        or manifest.get("role_assignment") != "engine_selected_private"
        or manifest.get("stop_boundary") != "existing_stage_2_input"
    ):
        raise ExperimentSafetyError("Qualification input or stop boundary changed")
    if manifest.get("model_order") != ["flash", "pro"] or manifest.get("models") != EXPECTED_MODELS:
        raise ExperimentSafetyError("Qualification model order or exact slugs changed")
    limits = manifest.get("limits")
    if not isinstance(limits, Mapping) or limits != {
        "initial_attempts_per_model": 3,
        "delta_repairs_per_parsed_candidate": 2,
        "semantic_plan_max_tokens": STAGE1_PLAN_MAX_TOKENS,
        "syntax_repair_max_tokens": STAGE1_SYNTAX_REPAIR_MAX_TOKENS,
        "delta_repair_max_tokens": STAGE1_REPAIR_MAX_TOKENS,
    }:
        raise ExperimentSafetyError("Qualification attempt or output limits changed")
    budget = manifest.get("budget")
    if not isinstance(budget, Mapping) or budget != {
        "namespace": "stage1_semantic_qualification",
        "fresh_budget_usd": "10.00",
        "soft_stop_usd": "8.50",
        "hard_stop_usd": "9.50",
        "uncertainty_reserve_usd": "0.50",
    }:
        raise ExperimentSafetyError("Qualification budget policy changed")
    if manifest.get("reasoning") != {
        "semantic_plan": "high",
        "syntax_repair": "disabled",
        "delta_repair": "disabled",
    }:
        raise ExperimentSafetyError("Qualification reasoning policy changed")
    character_ids = manifest.get("character_ids")
    seed = manifest.get("seed")
    if not isinstance(character_ids, list) or len(character_ids) != 8 or len(set(character_ids)) != 8:
        raise ExperimentSafetyError("Qualification cast must contain eight unique IDs")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ExperimentSafetyError("Qualification seed is invalid")
    roles = select_stage1_roles(
        character_ids=tuple(character_ids),
        seed=seed,
        death_mode=str(manifest.get("death_mode")),
    )
    if role_assignment_fingerprint(roles) != manifest.get("role_assignment_fingerprint"):
        raise ExperimentSafetyError("Frozen role-assignment fingerprint changed")
    if roles.victim_id == roles.responsible_actor_id or roles.discoverer_id == roles.victim_id:
        raise ExperimentSafetyError("Qualification roles violate homicide constraints")


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
        raise ExperimentSafetyError("Qualification is running from the wrong branch")
    if require_clean and _git_output("status", "--porcelain=v1"):
        raise ExperimentSafetyError("Paid qualification requires a clean exact commit")
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
                "Stage 1 qualification safety gate stopped execution",
                code="experiment_safety_stop",
                retryable=False,
            ) from error

    return callback


def _clients(
    *,
    api_key: str,
    model: str,
    observer: DeepSeekRequestObserver,
) -> tuple[LLMClient, LLMClient]:
    callback = _safe_callback(observer)
    plan = LLMClient(
        api_key=api_key,
        model=model,
        transport="deepseek_direct",
        reasoning_effort="high",
        request_observer=callback,
        temperature=0.55,
        top_p=0.95,
        top_k=None,
        max_tokens=STAGE1_PLAN_MAX_TOKENS,
        task_max_tokens={"stage1_semantic_plan": STAGE1_PLAN_MAX_TOKENS},
    )
    repair = LLMClient(
        api_key=api_key,
        model=model,
        transport="deepseek_direct",
        reasoning_effort=None,
        request_observer=callback,
        temperature=0.0,
        top_p=1.0,
        top_k=None,
        max_tokens=STAGE1_SYNTAX_REPAIR_MAX_TOKENS,
        task_max_tokens={
            "stage1_semantic_syntax_repair": STAGE1_SYNTAX_REPAIR_MAX_TOKENS,
            "stage1_semantic_delta_repair": STAGE1_REPAIR_MAX_TOKENS,
        },
    )
    return plan, repair


def _json_ready(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _existing_results() -> dict[str, Any]:
    if not RESULTS_PATH.is_file():
        return {"schema_version": 1, "status": "running", "model_results": []}
    value = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("model_results"), list):
        raise ExperimentSafetyError("Existing qualification results are malformed")
    return value


async def _run_model(
    *,
    manifest: Mapping[str, Any],
    model_key: str,
    git_sha: str,
    ledger: DeepSeekExperimentLedger,
    api_key: str,
) -> dict[str, Any]:
    model = EXPECTED_MODELS[model_key]
    run_id = f"stage1-semantic-{model_key}"
    observer = DeepSeekRequestObserver(
        ledger=ledger,
        metrics_path=REQUESTS_PATH,
        context=RunContext(
            experiment_revision=11,
            git_sha=git_sha,
            run_id=run_id,
            phase="stage1_qualification",
            pair_id="Q1",
            case_fingerprint=str(manifest["role_assignment_fingerprint"]),
        ),
        reasoning_by_task_role={
            "stage1_semantic_plan": "high",
            "stage1_semantic_syntax_repair": None,
            "stage1_semantic_delta_repair": None,
        },
    )
    plan_client, repair_client = _clients(
        api_key=api_key,
        model=model,
        observer=observer,
    )
    character_ids = tuple(str(value) for value in manifest["character_ids"])
    seed = int(manifest["seed"])
    location = load_location(str(manifest["location_id"]))
    roles = select_stage1_roles(
        character_ids=character_ids,
        seed=seed,
        death_mode=str(manifest["death_mode"]),
    )
    diagnostics: list[dict[str, object]] = []

    def record_attempt(record: dict[str, object]) -> None:
        enriched = {
            "schema_version": 1,
            "recorded_at": datetime.now(UTC).isoformat(),
            "experiment_revision": 11,
            "git_sha": git_sha,
            "model_key": model_key,
            "model": model,
            **record,
        }
        diagnostics.append(enriched)
        _append_jsonl(ATTEMPTS_PATH, enriched)

    accepted: dict[str, object] = {}

    def record_accepted(record: dict[str, object]) -> None:
        accepted.clear()
        accepted.update(record)

    core_holder: dict[str, object] = {}

    def validate_compiled(document: dict[str, object]) -> None:
        core = GeneratedCrimeTimelineStage.model_validate(document)
        _validate_core_stage(core, character_ids=character_ids, location=location)
        catalog = build_proof_support_catalog(core)
        if {candidate.axis for candidate in catalog.candidates.values()} != {
            "method",
            "motive",
            "opportunity",
        }:
            raise Stage1SemanticError(
                "compiled Stage 1 lacks a complete proof-support catalogue",
                code="incomplete_proof_support_catalog",
            )
        core_holder["core"] = core
        core_holder["catalog"] = catalog

    started_at = datetime.now(UTC).isoformat()
    try:
        boundary = await generate_stage1_boundary(
            plan_client,
            character_ids=character_ids,
            location=location,
            seed=seed,
            assignment=roles,
            repair_llm=repair_client,
            max_initial_attempts=int(manifest["limits"]["initial_attempts_per_model"]),
            max_delta_repairs=int(manifest["limits"]["delta_repairs_per_parsed_candidate"]),
            compiled_validator=validate_compiled,
            attempt_observer=record_attempt,
            accepted_stage_observer=record_accepted,
        )
    except Stage1SemanticError as error:
        if error.code == "experiment_safety_stop":
            raise ExperimentSafetyError(
                "Stage 1 qualification stopped at an accounting or request safety gate"
            ) from error
        return {
            "model_key": model_key,
            "model": model,
            "status": "failed",
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "failure_code": error.code,
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
    core = core_holder["core"]
    catalog = core_holder["catalog"]
    private_document = {
        "schema_version": 1,
        "experiment_revision": 11,
        "git_sha": git_sha,
        "model_key": model_key,
        "model": model,
        "role_assignment": roles.model_dump(mode="json"),
        "role_assignment_fingerprint": boundary.role_assignment_fingerprint,
        "semantic_plan": boundary.semantic_plan.model_dump(mode="json"),
        "semantic_plan_fingerprint": boundary.semantic_plan_fingerprint,
        "compiled_stage_1": core.model_dump(mode="json"),
        "compiled_stage_1_fingerprint": boundary.compiled_fingerprint,
        "proof_support_catalog": catalog.model_dump(mode="json"),
        "proof_support_catalog_fingerprint": proof_support_catalog_fingerprint(catalog),
        "accepted_observer_record": accepted,
    }
    _atomic_json(ARTIFACT_ROOT / f"accepted_{model_key}.json", private_document)
    return {
        "model_key": model_key,
        "model": model,
        "status": "passed_stage_1",
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "semantic_plan_fingerprint": boundary.semantic_plan_fingerprint,
        "compiled_stage_1_fingerprint": boundary.compiled_fingerprint,
        "proof_support_catalog_fingerprint": proof_support_catalog_fingerprint(catalog),
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


async def run_paid_qualification(manifest: Mapping[str, Any]) -> dict[str, Any]:
    branch, git_sha = qualification_git_identity(require_clean=True)
    ledger = DeepSeekExperimentLedger(
        LEDGER_PATH,
        policy=Stage1QualificationPolicy(),
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
        "manifest_path": str(MANIFEST_PATH.relative_to(REPOSITORY_ROOT)),
        "manifest_fingerprint": __import__("hashlib").sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "role_assignment_fingerprint": manifest["role_assignment_fingerprint"],
        "model_order": manifest["model_order"],
        "stop_boundary": manifest["stop_boundary"],
    }
    _atomic_json(PLAN_PATH, plan)
    api_key = load_direct_api_key()
    model_results: list[dict[str, Any]] = []
    for model_key in manifest["model_order"]:
        prior = existing_by_model.get(model_key)
        if isinstance(prior, dict) and prior.get("status") in {"passed_stage_1", "failed"}:
            model_results.append(prior)
            continue
        result = await _run_model(
            manifest=manifest,
            model_key=str(model_key),
            git_sha=git_sha,
            ledger=ledger,
            api_key=api_key,
        )
        model_results.append(result)
        snapshot = _json_ready(ledger.snapshot())
        _atomic_json(
            RESULTS_PATH,
            {
                "schema_version": 1,
                "status": "running",
                "created_at": plan["created_at"],
                "updated_at": datetime.now(UTC).isoformat(),
                "branch": branch,
                "git_sha": git_sha,
                "role_assignment_fingerprint": manifest["role_assignment_fingerprint"],
                "model_results": model_results,
                "budget": snapshot,
            },
        )
    passed = {
        item["model_key"]
        for item in model_results
        if item.get("status") == "passed_stage_1"
    }
    status = "completed" if passed == {"flash", "pro"} else "completed_with_failures"
    results = {
        "schema_version": 1,
        "status": status,
        "created_at": plan["created_at"],
        "completed_at": datetime.now(UTC).isoformat(),
        "branch": branch,
        "git_sha": git_sha,
        "role_assignment_fingerprint": manifest["role_assignment_fingerprint"],
        "model_results": model_results,
        "budget": _json_ready(ledger.snapshot()),
        "stage_2_requests": 0,
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
    manifest = _load_manifest()
    validate_manifest(manifest)
    branch, sha = qualification_git_identity(require_clean=args.execute)
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "ready",
                    "branch": branch,
                    "git_sha": sha,
                    "manifest": str(MANIFEST_PATH.relative_to(REPOSITORY_ROOT)),
                    "role_assignment_fingerprint": manifest["role_assignment_fingerprint"],
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
