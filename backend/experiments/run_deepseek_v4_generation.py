"""Run the frozen paired DeepSeek case-generation matrix through production admission."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from experiments.deepseek_v4_runner import (
    EXPECTED_MODELS,
    EXPECTED_MANIFEST_REVISION,
    EXPECTED_REPLACED_PAIR_ID,
    EXPECTED_REVISION10_PAIR_IDS,
    PRIVATE_ARTIFACT_ROOT,
    ExperimentSafetyError,
    build_request,
    load_manifest,
    load_private_preflights,
    resolve_clean_git_sha,
    validate_manifest,
    verify_preflights,
)
from experiments.deepseek_v4_runtime import (
    DeepSeekRequestObserver,
    RunContext,
    build_measured_client,
    load_direct_api_key,
)
from game.case_generation import GeneratedScenarioError
from game.persistence import snapshot_engine
from game.recipes import case_content_fingerprint
from game.service import GameService
from llm.experiment import DeepSeekExperimentLedger


ClientBuilder = Callable[..., Any]
ServiceBuilder = Callable[[Path, Any], GameService]


def _atomic_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        with path.open("r+b") as handle:
            os.fsync(handle.fileno())
    except OSError as error:
        raise ExperimentSafetyError("Could not durably persist generation control state.") from error


def _append_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _load_json(path: Path, *, description: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentSafetyError(f"{description} could not be read safely.") from error
    if not isinstance(document, dict):
        raise ExperimentSafetyError(f"{description} has an invalid schema.")
    return document


def _has_generation_intent(path: Path, *, experiment_revision: int) -> bool:
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ExperimentSafetyError("Generation request-intent journal could not be read.") from error
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ExperimentSafetyError("Generation request-intent journal is malformed.") from error
        if not isinstance(record, Mapping) or record.get("schema_version") != 1:
            raise ExperimentSafetyError("Generation request-intent journal has an invalid schema.")
        if (
            record.get("experiment_revision") == experiment_revision
            and record.get("phase") == "generation"
        ):
            return True
    return False


def _execution_identity(
    *,
    manifest: Mapping[str, Any],
    git_sha: str,
) -> dict[str, Any]:
    return {
        "experiment_revision": int(manifest["manifest_revision"]),
        "git_sha": git_sha,
        "manifest_sha256": _manifest_digest(manifest),
        "pair_ids": list(EXPECTED_REVISION10_PAIR_IDS),
        "reserve_activation": {
            "reserve_pair_id": "R1",
            "replaces_pair_id": EXPECTED_REPLACED_PAIR_ID,
            "invalidated_cell": "P1",
            "reason": "revision_6_controller_interruption",
        },
    }


def _verify_execution_identity(
    document: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    description: str,
) -> None:
    for key, value in expected.items():
        if document.get(key) != value:
            raise ExperimentSafetyError(f"{description} differs from the frozen revision-10 plan.")


def _expected_cells(manifest: Mapping[str, Any]) -> list[tuple[str, str]]:
    pairs = {
        str(pair["pair_id"]): pair
        for pair in [*manifest["generation_pairs"], manifest["reserve_pair"]]
    }
    return [
        (pair_id, str(model_key))
        for pair_id in EXPECTED_REVISION10_PAIR_IDS
        for model_key in pairs[pair_id]["model_order"]
    ]


def _candidate_attempt_record(
    *,
    manifest: Mapping[str, Any],
    git_sha: str,
    pair_id: str,
    model_key: str,
    diagnostic: Mapping[str, Any],
    observer: DeepSeekRequestObserver,
) -> dict[str, Any]:
    request_record = observer.last_record or {}
    return {
        "schema_version": 3,
        "experiment_revision": int(manifest["manifest_revision"]),
        "git_sha": git_sha,
        "pair_id": pair_id,
        "model_key": model_key,
        "model": EXPECTED_MODELS[model_key],
        "prompt_revision": manifest["prompt_revision"],
        "schema_revision": manifest["schema_revision"],
        "candidate_attempt": 1,
        "stage": diagnostic.get("stage"),
        "stage_attempt": diagnostic["attempt"],
        "admission_result": diagnostic["result"],
        "failure_category": diagnostic.get("failure_category"),
        "failure_code": diagnostic.get("failure_code"),
        "repair_feedback_used": diagnostic["repair_feedback_used"],
        "safe_detail": diagnostic.get("safe_detail"),
        "request_id": request_record.get("request_id"),
        "generation_id": request_record.get("generation_id"),
    }


def _default_service_builder(save_root: Path, scenario_llm: Any) -> GameService:
    return GameService(save_root, scenario_llm=scenario_llm)


def _money_total(records: Sequence[Mapping[str, Any]]) -> str:
    return format(
        sum(
            (
                Decimal(str(record["total_external_cost_usd"]))
                for record in records
                if record.get("result") == "success"
            ),
            Decimal("0"),
        ),
        "f",
    )


def _write_progress(
    path: Path,
    *,
    execution_identity: Mapping[str, Any],
    outcomes: Sequence[Mapping[str, Any]],
    ledger: DeepSeekExperimentLedger,
    status: str,
) -> None:
    snapshot = ledger.snapshot()
    _atomic_json(
        path,
        {
            "schema_version": 2,
            **dict(execution_identity),
            "status": status,
            "outcomes": list(outcomes),
            "budget": {
                "provider_confirmed_settled_usd": str(snapshot["settled_usd"]),
                "unsettled_worst_case_exposure_usd": str(snapshot["reserved_usd"]),
                "open_reservations": snapshot["open_reservations"],
                "available_before_soft_stop_after_conservative_holds_usd": str(
                    snapshot["available_before_soft_stop_usd"]
                ),
            },
        },
    )


async def run_generation_matrix(
    *,
    manifest: Mapping[str, Any],
    preflight_evidence: Mapping[str, Any],
    git_sha: str,
    api_key: str,
    artifact_root: Path = PRIVATE_ARTIFACT_ROOT,
    explicitly_enabled: bool,
    client_builder: ClientBuilder = build_measured_client,
    service_builder: ServiceBuilder = _default_service_builder,
    reserve_replaces_pair_id: str,
) -> list[dict[str, Any]]:
    """Generate each frozen cell once; the production generator owns its 1..3 attempts.

    Admission failures remain in the denominator and do not get an unplanned
    outer retry. Provider, accounting, exact-model, and budget failures stop the matrix.
    Canonical truth is written only below the ignored private artifact root.
    """

    validate_manifest(manifest)
    if not explicitly_enabled:
        raise ExperimentSafetyError("Generation traffic requires an explicit opt-in.")
    if not api_key:
        raise ExperimentSafetyError("A direct DeepSeek credential is required.")
    verify_preflights(preflight_evidence, manifest, expected_git_sha=git_sha)

    if reserve_replaces_pair_id != EXPECTED_REPLACED_PAIR_ID:
        raise ExperimentSafetyError(
            "Revision 10 permits only the predeclared R1 replacement for interrupted pair P1."
        )
    declared_pairs = {
        str(pair["pair_id"]): pair
        for pair in [*manifest["generation_pairs"], manifest["reserve_pair"]]
    }
    selected_pairs = [declared_pairs[pair_id] for pair_id in EXPECTED_REVISION10_PAIR_IDS]
    reserve_pair_id = "R1"

    execution_identity = _execution_identity(manifest=manifest, git_sha=git_sha)
    plan_path = artifact_root / "generation_plan.json"
    progress_path = artifact_root / "generation_results.json"
    intent_path = artifact_root / "request_intents.jsonl"
    if plan_path.exists():
        plan = _load_json(plan_path, description="Generation execution plan")
        _verify_execution_identity(
            plan,
            execution_identity,
            description="Generation execution plan",
        )
        if plan.get("status") != "completed":
            raise ExperimentSafetyError(
                "An incomplete generation execution already exists; manual reconciliation is "
                "required before any duplicate provider traffic."
            )
        results = _load_json(progress_path, description="Completed generation results")
        _verify_execution_identity(
            results,
            execution_identity,
            description="Completed generation results",
        )
        outcomes = results.get("outcomes")
        expected_cells = _expected_cells(manifest)
        if (
            results.get("status") != "completed"
            or not isinstance(outcomes, list)
            or len(outcomes) != len(expected_cells)
            or not all(isinstance(outcome, Mapping) for outcome in outcomes)
        ):
            raise ExperimentSafetyError("Completed generation outcomes are missing.")
        observed_cells = [
            (str(outcome.get("pair_id", "")), str(outcome.get("model_key", "")))
            for outcome in outcomes
        ]
        if observed_cells != expected_cells:
            raise ExperimentSafetyError("Completed generation outcomes do not match the frozen matrix.")
        return [dict(outcome) for outcome in outcomes]
    if _has_generation_intent(
        intent_path,
        experiment_revision=EXPECTED_MANIFEST_REVISION,
    ):
        raise ExperimentSafetyError(
            "A revision-10 generation request intent exists without its execution plan; manual "
            "reconciliation is required before provider traffic."
        )
    if progress_path.exists():
        raise ExperimentSafetyError(
            "Generation results exist without a revision-10 execution plan; archive or reconcile "
            "them before provider traffic."
        )

    plan: dict[str, Any] = {
        "schema_version": 1,
        **execution_identity,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "current_cell": None,
        "completed_cells": [],
        "request_events": 0,
        "attempt_events": 0,
    }
    _atomic_json(plan_path, plan)

    ledger = DeepSeekExperimentLedger(artifact_root / "cost_ledger.jsonl")
    metrics_path = artifact_root / "requests.jsonl"
    outcomes: list[dict[str, Any]] = []
    _write_progress(
        progress_path,
        execution_identity=execution_identity,
        outcomes=outcomes,
        ledger=ledger,
        status="running",
    )

    for pair in selected_pairs:
        pair_id = str(pair["pair_id"])
        for model_key in pair["model_order"]:
            model_key = str(model_key)
            request = build_request(
                manifest,
                model_key,
                task_role="case_generation_proof_blueprint",
            )
            run_id = f"generation-{pair_id}-{model_key}"
            plan["current_cell"] = {
                "pair_id": pair_id,
                "model_key": model_key,
                "run_id": run_id,
                "started_at": datetime.now(UTC).isoformat(),
            }
            _atomic_json(plan_path, plan)

            def record_request_event(record: Mapping[str, Any]) -> None:
                plan["request_events"] = int(plan["request_events"]) + 1
                plan["last_request"] = {
                    "pair_id": pair_id,
                    "model_key": model_key,
                    "task_role": record.get("task_role"),
                    "request_id": record.get("request_id"),
                    "generation_id": record.get("generation_id"),
                    "result": record.get("result"),
                }
                _atomic_json(plan_path, plan)

            observer = DeepSeekRequestObserver(
                ledger=ledger,
                metrics_path=metrics_path,
                context=RunContext(
                    int(manifest["manifest_revision"]),
                    git_sha,
                    run_id,
                    "generation",
                    pair_id,
                ),
                record_observer=record_request_event,
            )
            client = client_builder(
                api_key=api_key,
                model=request.model,
                observer=observer,
            )
            cell_root = artifact_root / "generation_cells" / run_id
            service = service_builder(cell_root / "saves", client)
            attempt_records: list[dict[str, Any]] = []
            accepted_stage_path = cell_root / "accepted_stages.json"
            accepted_stage_state: dict[str, Any] = {
                "schema_version": 1,
                **execution_identity,
                "pair_id": pair_id,
                "model_key": model_key,
                "model": EXPECTED_MODELS[model_key],
                "seed": int(pair["seed"]),
                "cast_ids": list(pair["cast_ids"]),
                "location_id": manifest["location_package_id"],
                "stages": {},
            }

            def record_attempt(diagnostic: dict[str, object]) -> None:
                record = _candidate_attempt_record(
                    manifest=manifest,
                    git_sha=git_sha,
                    pair_id=pair_id,
                    model_key=model_key,
                    diagnostic=diagnostic,
                    observer=observer,
                )
                _append_jsonl(
                    artifact_root / "generation_attempts.jsonl",
                    [record],
                )
                attempt_records.append(record)
                plan["attempt_events"] = int(plan["attempt_events"]) + 1
                plan["last_attempt"] = {
                    "pair_id": pair_id,
                    "model_key": model_key,
                    "stage": record.get("stage"),
                    "stage_attempt": record.get("stage_attempt"),
                    "admission_result": record.get("admission_result"),
                }
                _atomic_json(plan_path, plan)

            service.set_generation_attempt_observer(record_attempt)

            def record_accepted_stage(record: dict[str, object]) -> None:
                stage = record.get("stage")
                document = record.get("document")
                fingerprint = record.get("stage_fingerprint")
                if not isinstance(stage, str) or not isinstance(document, Mapping):
                    raise ExperimentSafetyError("Accepted stage observer received invalid state.")
                if fingerprint != _manifest_digest(document):
                    raise ExperimentSafetyError("Accepted stage fingerprint does not match its document.")
                stages = accepted_stage_state["stages"]
                if not isinstance(stages, dict):
                    raise ExperimentSafetyError("Accepted stage state is malformed.")
                existing = stages.get(stage)
                stage_record = {
                    "stage_fingerprint": fingerprint,
                    "stage_attempt": record.get("stage_attempt"),
                    "source": record.get("source"),
                    "request_id": (observer.last_record or {}).get("request_id"),
                    "generation_id": (observer.last_record or {}).get("generation_id"),
                    "actual_model": (observer.last_record or {}).get("actual_model"),
                    "proof_catalog_fingerprint": record.get("proof_catalog_fingerprint"),
                    "document": dict(document),
                }
                if existing is not None and existing != stage_record:
                    raise ExperimentSafetyError("An accepted stage was rewritten within one cell.")
                stages[stage] = stage_record
                accepted_stage_state["updated_at"] = datetime.now(UTC).isoformat()
                _atomic_json(accepted_stage_path, accepted_stage_state)

            service.set_generation_stage_observer(record_accepted_stage)
            outcome: dict[str, Any] = {
                "pair_id": pair_id,
                "model_key": model_key,
                "model": EXPECTED_MODELS[str(model_key)],
                "seed": int(pair["seed"]),
                "cast_ids": list(pair["cast_ids"]),
                "location_id": manifest["location_package_id"],
            }
            if pair_id == reserve_pair_id:
                outcome["reserve_replaces_pair_id"] = reserve_replaces_pair_id
            try:
                try:
                    await service.start_generated_async(
                        seed=int(pair["seed"]),
                        location_id=str(manifest["location_package_id"]),
                        character_ids=tuple(str(value) for value in pair["cast_ids"]),
                        difficulty="normal",
                    )
                except GeneratedScenarioError as error:
                    if error.code != "invalid_generated_case":
                        raise ExperimentSafetyError(
                            f"Provider execution stopped during {run_id}: {error.code}."
                        ) from error
                    outcome.update(
                        {
                            "admitted": False,
                            "candidate_attempts": 1,
                            "stage_requests": len(attempt_records),
                            "failed_stage": (
                                attempt_records[-1].get("stage")
                                if attempt_records
                                else None
                            ),
                            "failure_code": error.code,
                            "measured_external_cost_usd": _money_total(observer.records),
                        }
                    )
                else:
                    if service.engine is None:
                        raise ExperimentSafetyError(
                            "Generated service returned without canonical truth."
                        )
                    fingerprint = case_content_fingerprint(service.engine.case)
                    canonical_path = cell_root / "canonical_snapshot.json"
                    _atomic_json(
                        canonical_path,
                        snapshot_engine(service.engine).model_dump(mode="json"),
                    )
                    outcome.update(
                        {
                            "admitted": True,
                            "candidate_attempts": 1,
                            "stage_requests": len(attempt_records),
                            "case_id": service.engine.case.id,
                            "case_fingerprint": fingerprint,
                            "canonical_artifact": str(
                                canonical_path.relative_to(artifact_root)
                            ),
                            "measured_external_cost_usd": _money_total(observer.records),
                        }
                    )
            except BaseException as error:
                plan["status"] = "safety_stopped"
                plan["stopped_at"] = datetime.now(UTC).isoformat()
                plan["last_error_type"] = type(error).__name__
                _atomic_json(plan_path, plan)
                _write_progress(
                    progress_path,
                    execution_identity=execution_identity,
                    outcomes=outcomes,
                    ledger=ledger,
                    status="safety_stopped",
                )
                raise
            if accepted_stage_path.is_file():
                outcome["accepted_stage_artifact"] = str(
                    accepted_stage_path.relative_to(artifact_root)
                )
            outcomes.append(outcome)
            plan["completed_cells"].append({"pair_id": pair_id, "model_key": model_key})
            plan["current_cell"] = None
            _write_progress(
                progress_path,
                execution_identity=execution_identity,
                outcomes=outcomes,
                ledger=ledger,
                status="running",
            )
            _atomic_json(plan_path, plan)
    plan["status"] = "completed"
    plan["completed_at"] = datetime.now(UTC).isoformat()
    _write_progress(
        progress_path,
        execution_identity=execution_identity,
        outcomes=outcomes,
        ledger=ledger,
        status="completed",
    )
    _atomic_json(plan_path, plan)
    return outcomes


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen revision-10 P2/P3/R1 DeepSeek matrix sequentially."
    )
    parser.add_argument("--activate-reserve", action="store_true", required=True)
    parser.add_argument("--reserve-replaces", choices=("P1",), required=True)
    return parser.parse_args(argv)


async def main(argv: Sequence[str] | None = None) -> int:
    if os.environ.get("AI_MYSTERY_ENABLE_DEEPSEEK_GENERATION") != "1":
        raise RuntimeError("Set the explicit generation enable flag to run provider traffic.")
    manifest = load_manifest()
    options = parse_args(argv)
    if not options.activate_reserve:
        raise ExperimentSafetyError("Revision 10 requires explicit reserve activation.")
    git_sha = resolve_clean_git_sha()
    preflights = load_private_preflights(PRIVATE_ARTIFACT_ROOT / "verified_preflights.json")
    api_key = load_direct_api_key()
    outcomes = await run_generation_matrix(
        manifest=manifest,
        preflight_evidence=preflights,
        git_sha=git_sha,
        api_key=api_key,
        explicitly_enabled=True,
        reserve_replaces_pair_id=options.reserve_replaces,
    )
    print(
        json.dumps(
            {
                "cells_completed": len(outcomes),
                "admitted": sum(bool(outcome["admitted"]) for outcome in outcomes),
                "rejected": sum(not bool(outcome["admitted"]) for outcome in outcomes),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
