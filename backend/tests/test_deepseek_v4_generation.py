"""Offline production-path tests for the paid paired-generation runner."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import uuid

import pytest

from conftest import SemanticScenarioFixture, make_dummy_generated_document
from experiments.run_deepseek_v4_generation import (
    _has_generation_intent,
    run_generation_matrix,
)
from experiments.deepseek_v4_runner import (
    EXPECTED_MODELS,
    ExperimentSafetyError,
    load_manifest,
)
from llm.client import LLMResponse


GIT_SHA = "b" * 40


def _preflights() -> dict[str, object]:
    return {
        key: {
            "experiment_revision": 10,
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


class _OfflineMeasuredClient:
    def __init__(self, *, model: str, observer, content_factory) -> None:
        self.model = model
        self.observer = observer
        self.content_factory = content_factory
        self.calls = 0

    async def generate(self, messages, **kwargs) -> LLMResponse:
        assert kwargs["task_role"] in {
            "stage1_semantic_plan",
            "case_generation_proof_blueprint",
            "case_generation_evidence_realization",
            "case_generation_misdirection",
            "case_generation_overlays",
            "case_generation_presentation",
        }
        self.calls += 1
        transport_request_id = uuid.uuid4().hex
        event = {
            "request_id": transport_request_id,
            "model": self.model,
            "task_role": kwargs["task_role"],
            "max_tokens": kwargs["max_tokens"],
            "prompt_tokens_upper_bound": sum(len(message.content) for message in messages),
            "provider_routing": None,
            "reasoning_effort": "high",
            "transport": "deepseek_direct",
        }
        await self.observer("pre_call", event)
        content = self.content_factory(messages, kwargs["task_role"])
        if not isinstance(content, str):
            content = json.dumps(content)
        response = LLMResponse(
            content=content,
            id=f"generation-{uuid.uuid4().hex}",
            model=self.model,
            provider="DeepSeek",
            prompt_tokens=100,
            prompt_cache_miss_tokens=100,
            completion_tokens=200,
            reported_total_tokens=300,
            reasoning_tokens=50,
            wall_latency_seconds=0.01,
        )
        await self.observer(
            "response",
            {
                **event,
                "response": response,
                "error": None,
                "cancelled": False,
            },
        )
        return response


def test_generation_matrix_uses_production_admission_and_private_snapshots(
    tmp_path: Path,
) -> None:
    manifest = load_manifest()
    pairs_by_id = {
        pair["pair_id"]: pair
        for pair in [*manifest["generation_pairs"], manifest["reserve_pair"]]
    }
    planned_pairs = [pairs_by_id[pair_id] for pair_id in ("P2", "P3", "R1")]
    clients_built = 0

    def client_builder(*, api_key, model, observer):
        nonlocal clients_built
        assert api_key == "test-gateway-credential"
        pair = planned_pairs[clients_built // 2]
        clients_built += 1
        document = make_dummy_generated_document(character_ids=tuple(pair["cast_ids"]))
        scenario = SemanticScenarioFixture(document)

        def content_factory(messages, role):
            return scenario.response(messages, role)

        return _OfflineMeasuredClient(
            model=model,
            observer=observer,
            content_factory=content_factory,
        )

    outcomes = asyncio.run(
        run_generation_matrix(
            manifest=manifest,
            preflight_evidence=_preflights(),
            git_sha=GIT_SHA,
            api_key="test-gateway-credential",
            artifact_root=tmp_path,
            explicitly_enabled=True,
            client_builder=client_builder,
            reserve_replaces_pair_id="P1",
        )
    )

    assert [(outcome["pair_id"], outcome["model_key"]) for outcome in outcomes] == [
        (pair["pair_id"], model_key)
        for pair in planned_pairs
        for model_key in pair["model_order"]
    ]
    assert clients_built == 6
    assert all(outcome["admitted"] is True for outcome in outcomes)
    assert all(outcome["candidate_attempts"] == 1 for outcome in outcomes)
    assert all(outcome["stage_requests"] == 6 for outcome in outcomes)
    assert all(len(outcome["case_fingerprint"]) == 64 for outcome in outcomes)
    assert all((tmp_path / outcome["canonical_artifact"]).is_file() for outcome in outcomes)
    accepted_stage_states = [
        json.loads((tmp_path / outcome["accepted_stage_artifact"]).read_text(encoding="utf-8"))
        for outcome in outcomes
    ]
    assert all(
        set(state["stages"])
        == {
            "case_generation_core",
            "case_generation_proof_blueprint",
            "case_generation_proof_blueprint_compiled",
            "case_generation_evidence_realization",
            "case_generation_misdirection",
            "case_generation_overlays",
            "case_generation_presentation",
        }
        for state in accepted_stage_states
    )
    assert all(
        len(stage["stage_fingerprint"]) == 64
        and isinstance(stage["document"], dict)
        and stage["actual_model"] == state["model"]
        for state in accepted_stage_states
        for stage in state["stages"].values()
    )
    progress = json.loads((tmp_path / "generation_results.json").read_text(encoding="utf-8"))
    assert progress["status"] == "completed"
    assert progress["pair_ids"] == ["P2", "P3", "R1"]
    assert progress["reserve_activation"]["replaces_pair_id"] == "P1"
    assert "provider_confirmed_settled_usd" in progress["budget"]
    assert "unsettled_worst_case_exposure_usd" in progress["budget"]
    assert "settled_usd" not in progress["budget"]
    assert len(progress["outcomes"]) == 6
    plan = json.loads((tmp_path / "generation_plan.json").read_text(encoding="utf-8"))
    assert plan["status"] == "completed"
    assert len(plan["completed_cells"]) == 6
    assert plan["request_events"] == 36
    assert plan["attempt_events"] == 36
    request_records = (tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(request_records) == 36
    request_intents = (tmp_path / "request_intents.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(request_intents) == 36
    assert {json.loads(record)["task_role"] for record in request_records} == {
        "stage1_semantic_plan",
        "case_generation_proof_blueprint",
        "case_generation_evidence_realization",
        "case_generation_misdirection",
        "case_generation_overlays",
        "case_generation_presentation",
    }
    attempts = [
        json.loads(record)
        for record in (tmp_path / "generation_attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(attempts) == 36
    assert all(record["admission_result"] == "admitted" for record in attempts)
    assert all(record["request_id"] and record["generation_id"] for record in attempts)

    built_on_repeat = False

    def forbidden_builder(**_kwargs):
        nonlocal built_on_repeat
        built_on_repeat = True

    repeated = asyncio.run(
        run_generation_matrix(
            manifest=manifest,
            preflight_evidence=_preflights(),
            git_sha=GIT_SHA,
            api_key="test-gateway-credential",
            artifact_root=tmp_path,
            explicitly_enabled=True,
            client_builder=forbidden_builder,
            reserve_replaces_pair_id="P1",
        )
    )
    assert repeated == outcomes
    assert built_on_repeat is False

    progress["outcomes"].append("forged-extra-cell")
    (tmp_path / "generation_results.json").write_text(
        json.dumps(progress),
        encoding="utf-8",
    )
    with pytest.raises(ExperimentSafetyError, match="outcomes are missing"):
        asyncio.run(
            run_generation_matrix(
                manifest=manifest,
                preflight_evidence=_preflights(),
                git_sha=GIT_SHA,
                api_key="test-gateway-credential",
                artifact_root=tmp_path,
                explicitly_enabled=True,
                client_builder=forbidden_builder,
                reserve_replaces_pair_id="P1",
            )
        )


def test_generation_matrix_counts_three_rejected_candidates_without_outer_retry(
    tmp_path: Path,
) -> None:
    manifest = load_manifest()

    def client_builder(*, api_key, model, observer):
        del api_key
        return _OfflineMeasuredClient(
            model=model,
            observer=observer,
            content_factory=lambda _messages, _role: "{not-json",
        )

    outcomes = asyncio.run(
        run_generation_matrix(
            manifest=manifest,
            preflight_evidence=_preflights(),
            git_sha=GIT_SHA,
            api_key="test-gateway-credential",
            artifact_root=tmp_path,
            explicitly_enabled=True,
            client_builder=client_builder,
            reserve_replaces_pair_id="P1",
        )
    )

    assert len(outcomes) == 6
    assert all(outcome["admitted"] is False for outcome in outcomes)
    assert all(outcome["candidate_attempts"] == 1 for outcome in outcomes)
    assert all(outcome["stage_requests"] == 3 for outcome in outcomes)
    assert all(outcome["failed_stage"] == "stage1_semantic_plan" for outcome in outcomes)
    assert all(outcome["failure_code"] == "malformed_json" for outcome in outcomes)
    assert len((tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()) == 18
    attempts = [
        json.loads(record)
        for record in (tmp_path / "generation_attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(attempts) == 18
    assert all(record["failure_category"] == "malformed_json" for record in attempts)
    assert [record["repair_feedback_used"] for record in attempts[:3]] == [False, False, False]
    assert all(record["candidate_attempt"] == 1 for record in attempts)
    assert [record["stage_attempt"] for record in attempts[:3]] == [1, 2, 3]


def test_generation_matrix_refuses_unverified_revision_before_building_client(
    tmp_path: Path,
) -> None:
    manifest = load_manifest()
    built = False

    def client_builder(**_kwargs):
        nonlocal built
        built = True

    with pytest.raises(ExperimentSafetyError, match="different code revision"):
        asyncio.run(
            run_generation_matrix(
                manifest=manifest,
                preflight_evidence=_preflights(),
                git_sha="c" * 40,
                api_key="test-gateway-credential",
                artifact_root=tmp_path,
                explicitly_enabled=True,
                client_builder=client_builder,
                reserve_replaces_pair_id="P1",
            )
        )
    assert built is False


def test_revision10_refuses_any_reserve_replacement_other_than_interrupted_p1(
    tmp_path: Path,
) -> None:
    manifest = load_manifest()
    built = False

    def forbidden_builder(**_kwargs):
        nonlocal built
        built = True

    with pytest.raises(ExperimentSafetyError, match="only the predeclared R1 replacement"):
        asyncio.run(
            run_generation_matrix(
                manifest=manifest,
                preflight_evidence=_preflights(),
                git_sha=GIT_SHA,
                api_key="test-gateway-credential",
                artifact_root=tmp_path,
                explicitly_enabled=True,
                client_builder=forbidden_builder,
                reserve_replaces_pair_id="P2",
            )
        )
    assert built is False


def test_revision10_orphan_guard_ignores_archived_revision7_8_and_9_intents(
    tmp_path: Path,
) -> None:
    intent_path = tmp_path / "request_intents.jsonl"
    intent_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment_revision": 7,
                "phase": "generation",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with intent_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "experiment_revision": 8,
                    "phase": "generation",
                }
            )
            + "\n"
        )

    with intent_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "experiment_revision": 9,
                    "phase": "generation",
                }
            )
            + "\n"
        )

    assert _has_generation_intent(intent_path, experiment_revision=10) is False

    with intent_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "experiment_revision": 10,
                    "phase": "generation",
                }
            )
            + "\n"
        )
    assert _has_generation_intent(intent_path, experiment_revision=10) is True


class _CrashAfterReservationClient:
    def __init__(self, *, model: str, observer) -> None:
        self.model = model
        self.observer = observer

    async def generate(self, messages, **kwargs):
        event = {
            "request_id": uuid.uuid4().hex,
            "model": self.model,
            "task_role": kwargs["task_role"],
            "max_tokens": kwargs["max_tokens"],
            "prompt_tokens_upper_bound": sum(len(message.content) for message in messages),
            "provider_routing": None,
            "reasoning_effort": "high",
            "transport": "deepseek_direct",
        }
        await self.observer("pre_call", event)
        raise asyncio.CancelledError


def test_interrupted_cell_is_durable_and_restart_refuses_duplicate_traffic(
    tmp_path: Path,
) -> None:
    manifest = load_manifest()

    def crashing_builder(*, api_key, model, observer):
        assert api_key == "test-gateway-credential"
        return _CrashAfterReservationClient(model=model, observer=observer)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_generation_matrix(
                manifest=manifest,
                preflight_evidence=_preflights(),
                git_sha=GIT_SHA,
                api_key="test-gateway-credential",
                artifact_root=tmp_path,
                explicitly_enabled=True,
                client_builder=crashing_builder,
                reserve_replaces_pair_id="P1",
            )
        )

    plan = json.loads((tmp_path / "generation_plan.json").read_text(encoding="utf-8"))
    assert plan["status"] == "safety_stopped"
    assert plan["current_cell"]["pair_id"] == "P2"
    assert plan["current_cell"]["model_key"] == "pro"
    progress = json.loads((tmp_path / "generation_results.json").read_text(encoding="utf-8"))
    assert progress["status"] == "safety_stopped"
    assert progress["outcomes"] == []
    assert progress["budget"]["open_reservations"] == 1

    built_on_restart = False

    def forbidden_builder(**_kwargs):
        nonlocal built_on_restart
        built_on_restart = True

    with pytest.raises(ExperimentSafetyError, match="manual reconciliation"):
        asyncio.run(
            run_generation_matrix(
                manifest=manifest,
                preflight_evidence=_preflights(),
                git_sha=GIT_SHA,
                api_key="test-gateway-credential",
                artifact_root=tmp_path,
                explicitly_enabled=True,
                client_builder=forbidden_builder,
                reserve_replaces_pair_id="P1",
            )
        )
    assert built_on_restart is False

    (tmp_path / "generation_plan.json").unlink()
    (tmp_path / "generation_results.json").unlink()
    with pytest.raises(ExperimentSafetyError, match="request intent exists"):
        asyncio.run(
            run_generation_matrix(
                manifest=manifest,
                preflight_evidence=_preflights(),
                git_sha=GIT_SHA,
                api_key="test-gateway-credential",
                artifact_root=tmp_path,
                explicitly_enabled=True,
                client_builder=forbidden_builder,
                reserve_replaces_pair_id="P1",
            )
        )
    assert built_on_restart is False
