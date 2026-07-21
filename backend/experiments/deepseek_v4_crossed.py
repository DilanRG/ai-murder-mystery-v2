"""Frozen crossed-case/NPC plan and pristine runtime restoration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
from typing import Any, Literal, Mapping, Sequence

from experiments.deepseek_v4_runner import (
    EXPECTED_MODELS,
    PRIVATE_ARTIFACT_ROOT,
    ExperimentSafetyError,
    validate_manifest,
    verify_preflights,
)
from experiments.deepseek_v4_runtime import (
    DeepSeekRequestObserver,
    RunContext,
    SequentialMeasuredClient,
    build_measured_client,
)
from game.persistence import SaveEnvelope
from game.recipes import case_content_fingerprint
from game.service import GameService
from llm.experiment import DeepSeekExperimentLedger


@dataclass(frozen=True)
class SelectedGeneratedCase:
    generation_model_key: str
    pair_id: str
    seed: int
    cast_ids: tuple[str, ...]
    case_fingerprint: str
    canonical_path: Path


@dataclass(frozen=True)
class CrossedCell:
    cell_id: str
    generated_case: SelectedGeneratedCase
    npc_model_key: str


@dataclass
class PreparedCrossedSession:
    cell: CrossedCell
    service: GameService
    measured_client: SequentialMeasuredClient


def _atomic_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_generation_results(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentSafetyError("Generation results could not be read.") from error
    if not isinstance(document, dict) or not isinstance(document.get("outcomes"), list):
        raise ExperimentSafetyError("Generation results have an invalid schema.")
    return document


def _private_artifact_path(value: object, artifact_root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ExperimentSafetyError("Admitted generation has no canonical artifact.")
    root = artifact_root.resolve()
    candidate = (artifact_root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ExperimentSafetyError("Canonical artifacts must stay below the private root.") from error
    if not candidate.is_file():
        raise ExperimentSafetyError("Canonical artifact is missing.")
    return candidate


def _validate_selected_outcome(
    outcome: Mapping[str, Any],
    *,
    pair: Mapping[str, Any],
    model_key: str,
    artifact_root: Path,
) -> SelectedGeneratedCase:
    if (
        outcome.get("admitted") is not True
        or outcome.get("pair_id") != pair["pair_id"]
        or outcome.get("model_key") != model_key
        or outcome.get("model") != EXPECTED_MODELS[model_key]
        or outcome.get("seed") != pair["seed"]
        or outcome.get("cast_ids") != pair["cast_ids"]
    ):
        raise ExperimentSafetyError("Admitted generation outcome differs from its frozen cell.")
    path = _private_artifact_path(outcome.get("canonical_artifact"), artifact_root)
    try:
        envelope = SaveEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ExperimentSafetyError("Canonical artifact is not a valid generated save.") from error
    case = envelope.generated_case
    if case is None or envelope.generated_case_fingerprint is None:
        raise ExperimentSafetyError("Canonical artifact does not embed generated truth.")
    fingerprint = case_content_fingerprint(case)
    if (
        fingerprint != envelope.generated_case_fingerprint
        or fingerprint != outcome.get("case_fingerprint")
        or case.seed != pair["seed"]
        or list(case.character_ids) != pair["cast_ids"]
        or case.location_package_id != outcome.get("location_id")
    ):
        raise ExperimentSafetyError("Canonical artifact identity does not match generation evidence.")
    return SelectedGeneratedCase(
        generation_model_key=model_key,
        pair_id=str(pair["pair_id"]),
        seed=int(pair["seed"]),
        cast_ids=tuple(str(value) for value in pair["cast_ids"]),
        case_fingerprint=fingerprint,
        canonical_path=path,
    )


def select_first_admitted_cases(
    *,
    manifest: Mapping[str, Any],
    generation_results: Mapping[str, Any],
    git_sha: str,
    artifact_root: Path = PRIVATE_ARTIFACT_ROOT,
) -> dict[str, SelectedGeneratedCase]:
    """Select first admitted Pro and Flash strictly in frozen manifest order."""

    validate_manifest(manifest)
    if generation_results.get("git_sha") != git_sha:
        raise ExperimentSafetyError("Generation results belong to a different code revision.")
    outcomes = generation_results.get("outcomes")
    if not isinstance(outcomes, list):
        raise ExperimentSafetyError("Generation outcomes are missing.")
    indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
    for raw in outcomes:
        if not isinstance(raw, Mapping):
            raise ExperimentSafetyError("Generation outcome is not an object.")
        key = (str(raw.get("pair_id", "")), str(raw.get("model_key", "")))
        if key in indexed:
            raise ExperimentSafetyError("Generation results contain a duplicate cell.")
        indexed[key] = raw

    selected: dict[str, SelectedGeneratedCase] = {}
    for model_key in ("pro", "flash"):
        for pair in manifest["generation_pairs"]:
            outcome = indexed.get((str(pair["pair_id"]), model_key))
            if outcome is not None and outcome.get("admitted") is True:
                selected[model_key] = _validate_selected_outcome(
                    outcome,
                    pair=pair,
                    model_key=model_key,
                    artifact_root=artifact_root,
                )
                break
        if model_key not in selected:
            raise ExperimentSafetyError(
                f"No admitted {model_key} case exists for the crossed comparison."
            )
    return selected


def build_crossed_cells(
    selected: Mapping[str, SelectedGeneratedCase],
) -> tuple[CrossedCell, ...]:
    if set(selected) != {"pro", "flash"}:
        raise ExperimentSafetyError("Crossed comparison needs one Pro and one Flash case.")
    return (
        CrossedCell("A", selected["pro"], "pro"),
        CrossedCell("B", selected["pro"], "flash"),
        CrossedCell("C", selected["flash"], "pro"),
        CrossedCell("D", selected["flash"], "flash"),
    )


def write_crossed_plan(
    path: Path,
    *,
    git_sha: str,
    cells: Sequence[CrossedCell],
) -> None:
    _atomic_json(
        path,
        {
            "schema_version": 1,
            "git_sha": git_sha,
            "selection_rule": "first_admitted_in_manifest_order",
            "cells": [
                {
                    "cell_id": cell.cell_id,
                    "generation_model_key": cell.generated_case.generation_model_key,
                    "npc_model_key": cell.npc_model_key,
                    "pair_id": cell.generated_case.pair_id,
                    "case_fingerprint": cell.generated_case.case_fingerprint,
                }
                for cell in cells
            ],
        },
    )


async def prepare_crossed_session(
    *,
    manifest: Mapping[str, Any],
    preflight_evidence: Mapping[str, Any],
    git_sha: str,
    api_key: str,
    cell: CrossedCell,
    artifact_root: Path = PRIVATE_ARTIFACT_ROOT,
    explicitly_enabled: bool,
    client_builder: Any = build_measured_client,
    phase: Literal["phase_a", "phase_b"] = "phase_a",
) -> PreparedCrossedSession:
    """Restore one pristine cell and assign every runtime model role identically."""

    validate_manifest(manifest)
    if not explicitly_enabled:
        raise ExperimentSafetyError("Crossed runtime requires explicit provider opt-in.")
    if not api_key:
        raise ExperimentSafetyError("An OpenRouter gateway credential is required.")
    verify_preflights(preflight_evidence, manifest, expected_git_sha=git_sha)
    if cell.npc_model_key not in EXPECTED_MODELS:
        raise ExperimentSafetyError("Crossed cell has an unapproved NPC model.")
    ledger = DeepSeekExperimentLedger(artifact_root / "cost_ledger.jsonl")
    observer = DeepSeekRequestObserver(
        ledger=ledger,
        metrics_path=artifact_root / "requests.jsonl",
        context=RunContext(
            int(manifest["manifest_revision"]),
            git_sha,
            f"{phase}-{cell.cell_id}",
            phase,
            cell.generated_case.pair_id,
            cell.generated_case.case_fingerprint,
        ),
    )
    inner = client_builder(
        api_key=api_key,
        model=EXPECTED_MODELS[cell.npc_model_key],
        observer=observer,
    )
    measured = SequentialMeasuredClient(inner)
    save_root = artifact_root / "runtime_cells" / phase / cell.cell_id / "saves"
    save_root.mkdir(parents=True, exist_ok=True)
    initial_name = "pristine-generated-case.json"
    initial_path = save_root / initial_name
    shutil.copyfile(cell.generated_case.canonical_path, initial_path)
    service = GameService(
        save_root,
        scenario_llm=None,
        npc_llm=measured,
        portrayal_llm=measured,
    )
    await service.load_async(initial_name)
    if (
        service.engine is None
        or case_content_fingerprint(service.engine.case)
        != cell.generated_case.case_fingerprint
    ):
        raise ExperimentSafetyError("Restored crossed cell changed canonical truth.")
    return PreparedCrossedSession(cell=cell, service=service, measured_client=measured)
