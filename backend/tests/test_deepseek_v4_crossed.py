"""Provider-free tests for frozen crossed runtime selection and restore."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from conftest import make_dummy_generated_document
from experiments.deepseek_v4_crossed import (
    build_crossed_cells,
    prepare_crossed_session,
    select_first_admitted_cases,
)
from experiments.deepseek_v4_runner import EXPECTED_MODELS, ExperimentSafetyError, load_manifest
from game.case_generation import compile_generated_scenario
from game.content import load_location
from game.engine import GameEngine
from game.persistence import snapshot_engine
from game.recipes import case_content_fingerprint


GIT_SHA = "d" * 40


def _preflights() -> dict[str, object]:
    return {
        key: {
            "experiment_revision": 6,
            "git_sha": GIT_SHA,
            "model": model,
            "actual_model": model,
            "upstream_provider": "deepseek",
            "transport": "deepseek_direct",
            "is_byok": None,
            "fallback_used": False,
            "accounting_mode": "direct_token_meter",
            "generation_id": f"preflight-{key}",
            "total_external_cost_usd": 0.001,
        }
        for key, model in EXPECTED_MODELS.items()
    }


def _admitted_outcome(
    root: Path,
    *,
    pair: dict[str, object],
    model_key: str,
) -> dict[str, object]:
    location = load_location("ashwick_manor")
    cast_ids = tuple(pair["cast_ids"])
    generated = compile_generated_scenario(
        make_dummy_generated_document(character_ids=cast_ids),
        character_ids=cast_ids,
        location=location,
        seed=int(pair["seed"]),
    )
    engine = GameEngine.create(
        generated.case,
        location,
        story_presentation=generated.presentation,
    )
    relative_path = Path("generation_cells") / f"{pair['pair_id']}-{model_key}.json"
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot_engine(engine).model_dump_json(indent=2), encoding="utf-8")
    return {
        "pair_id": pair["pair_id"],
        "model_key": model_key,
        "model": EXPECTED_MODELS[model_key],
        "seed": pair["seed"],
        "cast_ids": pair["cast_ids"],
        "location_id": "ashwick_manor",
        "admitted": True,
        "case_fingerprint": case_content_fingerprint(generated.case),
        "canonical_artifact": str(relative_path),
    }


def test_selector_uses_first_admitted_manifest_pair_not_results_order(tmp_path: Path) -> None:
    manifest = load_manifest()
    p1, p2, p3 = manifest["generation_pairs"]
    pro_later = _admitted_outcome(tmp_path, pair=p2, model_key="pro")
    pro_first = _admitted_outcome(tmp_path, pair=p1, model_key="pro")
    flash_first = _admitted_outcome(tmp_path, pair=p3, model_key="flash")
    results = {
        "git_sha": GIT_SHA,
        "outcomes": [pro_later, flash_first, pro_first],
    }

    selected = select_first_admitted_cases(
        manifest=manifest,
        generation_results=results,
        git_sha=GIT_SHA,
        artifact_root=tmp_path,
    )

    assert selected["pro"].pair_id == "P1"
    assert selected["flash"].pair_id == "P3"
    cells = build_crossed_cells(selected)
    assert [
        (cell.cell_id, cell.generated_case.generation_model_key, cell.npc_model_key)
        for cell in cells
    ] == [
        ("A", "pro", "pro"),
        ("B", "pro", "flash"),
        ("C", "flash", "pro"),
        ("D", "flash", "flash"),
    ]


def test_crossed_sessions_restore_pristine_truth_and_change_only_runtime_model(
    tmp_path: Path,
) -> None:
    manifest = load_manifest()
    pair = manifest["generation_pairs"][0]
    outcomes = [
        _admitted_outcome(tmp_path, pair=pair, model_key="pro"),
        _admitted_outcome(tmp_path, pair=pair, model_key="flash"),
    ]
    selected = select_first_admitted_cases(
        manifest=manifest,
        generation_results={"git_sha": GIT_SHA, "outcomes": outcomes},
        git_sha=GIT_SHA,
        artifact_root=tmp_path,
    )
    cells = build_crossed_cells(selected)
    source_bytes = selected["pro"].canonical_path.read_bytes()

    class OfflineClient:
        def __init__(self, model: str) -> None:
            self.model = model

    def client_builder(*, api_key, model, observer):
        assert api_key == "test-gateway-credential"
        assert observer.context.phase == "phase_a"
        return OfflineClient(model)

    async def prepare_both():
        first = await prepare_crossed_session(
            manifest=manifest,
            preflight_evidence=_preflights(),
            git_sha=GIT_SHA,
            api_key="test-gateway-credential",
            cell=cells[0],
            artifact_root=tmp_path,
            explicitly_enabled=True,
            client_builder=client_builder,
        )
        second = await prepare_crossed_session(
            manifest=manifest,
            preflight_evidence=_preflights(),
            git_sha=GIT_SHA,
            api_key="test-gateway-credential",
            cell=cells[1],
            artifact_root=tmp_path,
            explicitly_enabled=True,
            client_builder=client_builder,
        )
        return first, second

    first, second = asyncio.run(prepare_both())
    assert first.service.engine is not None and second.service.engine is not None
    assert first.service.engine.case == second.service.engine.case
    assert first.service.engine.runtime == second.service.engine.runtime
    assert first.measured_client.model == EXPECTED_MODELS["pro"]
    assert second.measured_client.model == EXPECTED_MODELS["flash"]
    assert first.service._npc_provider() is first.service._portrayal_provider()
    assert second.service._npc_provider() is second.service._portrayal_provider()
    assert selected["pro"].canonical_path.read_bytes() == source_bytes


def test_selector_rejects_canonical_artifact_path_escape(tmp_path: Path) -> None:
    manifest = load_manifest()
    pair = manifest["generation_pairs"][0]
    outcome = {
        "pair_id": pair["pair_id"],
        "model_key": "pro",
        "model": EXPECTED_MODELS["pro"],
        "seed": pair["seed"],
        "cast_ids": pair["cast_ids"],
        "location_id": "ashwick_manor",
        "admitted": True,
        "case_fingerprint": "0" * 64,
        "canonical_artifact": "../outside.json",
    }

    with pytest.raises(ExperimentSafetyError, match="private root"):
        select_first_admitted_cases(
            manifest=manifest,
            generation_results={"git_sha": GIT_SHA, "outcomes": [outcome]},
            git_sha=GIT_SHA,
            artifact_root=tmp_path,
        )
