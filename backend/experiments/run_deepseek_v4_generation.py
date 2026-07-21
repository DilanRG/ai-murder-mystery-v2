"""Run the frozen paired DeepSeek case-generation matrix through production admission."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any

from experiments.deepseek_v4_runner import (
    EXPECTED_MODELS,
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
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _persist_candidate_attempts(
    *,
    path: Path,
    manifest: Mapping[str, Any],
    git_sha: str,
    pair_id: str,
    model_key: str,
    service: GameService,
    observer: DeepSeekRequestObserver,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, diagnostic in enumerate(service.generation_attempt_diagnostics()):
        request_record = observer.records[index] if index < len(observer.records) else {}
        records.append(
            {
                "schema_version": 1,
                "experiment_revision": int(manifest["manifest_revision"]),
                "git_sha": git_sha,
                "pair_id": pair_id,
                "model_key": model_key,
                "model": EXPECTED_MODELS[model_key],
                "prompt_revision": manifest["prompt_revision"],
                "schema_revision": manifest["schema_revision"],
                "stage": diagnostic.get("stage"),
                "attempt": diagnostic["attempt"],
                "admission_result": diagnostic["result"],
                "failure_category": diagnostic.get("failure_category"),
                "failure_code": diagnostic.get("failure_code"),
                "repair_feedback_used": diagnostic["repair_feedback_used"],
                "safe_detail": diagnostic.get("safe_detail"),
                "request_id": request_record.get("request_id"),
                "generation_id": request_record.get("generation_id"),
            }
        )
    _append_jsonl(path, records)
    return records


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
    git_sha: str,
    outcomes: Sequence[Mapping[str, Any]],
    ledger: DeepSeekExperimentLedger,
) -> None:
    snapshot = ledger.snapshot()
    _atomic_json(
        path,
        {
            "schema_version": 1,
            "git_sha": git_sha,
            "outcomes": list(outcomes),
            "budget": {
                "settled_usd": str(snapshot["settled_usd"]),
                "reserved_usd": str(snapshot["reserved_usd"]),
                "open_reservations": snapshot["open_reservations"],
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
    pairs: Sequence[Mapping[str, Any]] | None = None,
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

    selected_pairs = list(pairs if pairs is not None else manifest["generation_pairs"])
    declared_pairs = {pair["pair_id"]: pair for pair in manifest["generation_pairs"]}
    for pair in selected_pairs:
        if pair.get("pair_id") not in declared_pairs or pair != declared_pairs[pair["pair_id"]]:
            raise ExperimentSafetyError("Only unchanged frozen generation pairs may run.")

    ledger = DeepSeekExperimentLedger(artifact_root / "cost_ledger.jsonl")
    metrics_path = artifact_root / "requests.jsonl"
    progress_path = artifact_root / "generation_results.json"
    outcomes: list[dict[str, Any]] = []

    for pair in selected_pairs:
        pair_id = str(pair["pair_id"])
        for model_key in pair["model_order"]:
            request = build_request(
                manifest,
                str(model_key),
                task_role="case_generation_core",
            )
            run_id = f"generation-{pair_id}-{model_key}"
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
            )
            client = client_builder(
                api_key=api_key,
                model=request.model,
                observer=observer,
            )
            cell_root = artifact_root / "generation_cells" / run_id
            service = service_builder(cell_root / "saves", client)
            outcome: dict[str, Any] = {
                "pair_id": pair_id,
                "model_key": model_key,
                "model": EXPECTED_MODELS[str(model_key)],
                "seed": int(pair["seed"]),
                "cast_ids": list(pair["cast_ids"]),
                "location_id": manifest["location_package_id"],
            }
            try:
                await service.start_generated_async(
                    seed=int(pair["seed"]),
                    location_id=str(manifest["location_package_id"]),
                    character_ids=tuple(str(value) for value in pair["cast_ids"]),
                    difficulty="normal",
                )
            except GeneratedScenarioError as error:
                attempt_records = _persist_candidate_attempts(
                    path=artifact_root / "generation_attempts.jsonl",
                    manifest=manifest,
                    git_sha=git_sha,
                    pair_id=pair_id,
                    model_key=str(model_key),
                    service=service,
                    observer=observer,
                )
                if error.code != "invalid_generated_case":
                    raise ExperimentSafetyError(
                        f"Provider execution stopped during {run_id}: {error.code}."
                    ) from error
                outcome.update(
                    {
                        "admitted": False,
                        "attempts": len(attempt_records),
                        "failure_code": error.code,
                        "measured_external_cost_usd": _money_total(observer.records),
                    }
                )
            else:
                attempt_records = _persist_candidate_attempts(
                    path=artifact_root / "generation_attempts.jsonl",
                    manifest=manifest,
                    git_sha=git_sha,
                    pair_id=pair_id,
                    model_key=str(model_key),
                    service=service,
                    observer=observer,
                )
                if service.engine is None:
                    raise ExperimentSafetyError("Generated service returned without canonical truth.")
                fingerprint = case_content_fingerprint(service.engine.case)
                canonical_path = cell_root / "canonical_snapshot.json"
                _atomic_json(
                    canonical_path,
                    snapshot_engine(service.engine).model_dump(mode="json"),
                )
                outcome.update(
                    {
                        "admitted": True,
                        "attempts": len(attempt_records),
                        "case_id": service.engine.case.id,
                        "case_fingerprint": fingerprint,
                        "canonical_artifact": str(canonical_path.relative_to(artifact_root)),
                        "measured_external_cost_usd": _money_total(observer.records),
                    }
                )
            outcomes.append(outcome)
            _write_progress(progress_path, git_sha=git_sha, outcomes=outcomes, ledger=ledger)
    return outcomes


async def main() -> int:
    if os.environ.get("AI_MYSTERY_ENABLE_DEEPSEEK_GENERATION") != "1":
        raise RuntimeError("Set the explicit generation enable flag to run provider traffic.")
    manifest = load_manifest()
    git_sha = resolve_clean_git_sha()
    preflights = load_private_preflights(PRIVATE_ARTIFACT_ROOT / "verified_preflights.json")
    api_key = load_direct_api_key()
    outcomes = await run_generation_matrix(
        manifest=manifest,
        preflight_evidence=preflights,
        git_sha=git_sha,
        api_key=api_key,
        explicitly_enabled=True,
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
