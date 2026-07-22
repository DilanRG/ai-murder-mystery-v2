"""Falsifiable provider-free tests for Revision 10 staged canonical generation."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from semantic_pipeline_fixture import semantic_pipeline_payloads

from game.case_generation import (
    GeneratedCrimeTimelineStage,
    GeneratedEvidenceRealizationStage,
    GenerationObserverError,
    GeneratedMisdirectionConnectiveStage,
    GeneratedOverlayKnowledgeStage,
    GeneratedProofRouteSelectionStage,
    GeneratedScenarioError,
    assemble_evidence_solution_stage,
    assemble_generated_case_blueprint,
    build_proof_support_catalog,
    compile_proof_route_selection,
    generate_validated_scenario,
    _validate_core_stage,
)
from game.content import load_case, load_location


TEST_SEED = 901


class ScriptedStageLLM:
    """Deterministic staged provider that records every chargeable request."""

    def __init__(self, outputs_by_role: dict[str, list[str | Exception]]) -> None:
        self.outputs_by_role = {
            role: list(outputs) for role, outputs in outputs_by_role.items()
        }
        self.calls: list[dict[str, object]] = []

    async def generate(self, messages, **kwargs):
        role = kwargs["task_role"]
        self.calls.append({"messages": messages, **kwargs})
        output = self.outputs_by_role[role].pop(0)
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(content=output)


def _stage_payloads() -> dict[str, dict[str, object]]:
    return semantic_pipeline_payloads(TEST_SEED)


def _json_stage_outputs(
    payloads: dict[str, dict[str, object]],
) -> dict[str, list[str | Exception]]:
    return {role: [json.dumps(payload)] for role, payload in payloads.items()}


def _roles(llm: ScriptedStageLLM) -> list[str]:
    return [str(call["task_role"]) for call in llm.calls]


def _parse_truth_stages():
    payloads = _stage_payloads()
    core = GeneratedCrimeTimelineStage.model_validate(payloads["case_generation_core"])
    selection = GeneratedProofRouteSelectionStage.model_validate(
        payloads["case_generation_proof_blueprint"]
    )
    catalog = build_proof_support_catalog(core)
    proof = compile_proof_route_selection(selection, catalog=catalog, core=core)
    realization = GeneratedEvidenceRealizationStage.model_validate(
        payloads["case_generation_evidence_realization"]
    )
    connective = GeneratedMisdirectionConnectiveStage.model_validate(
        payloads["case_generation_misdirection"]
    )
    evidence = assemble_evidence_solution_stage(
        proof,
        realization,
        connective,
        core=core,
        location=load_location("ashwick_manor"),
    )
    return payloads, core, evidence


def test_stage_assembly_derives_links_and_retains_causal_provenance() -> None:
    payloads, core, evidence = _parse_truth_stages()
    overlays = GeneratedOverlayKnowledgeStage.model_validate(
        payloads["case_generation_overlays"]
    )

    blueprint = assemble_generated_case_blueprint(core, evidence, overlays)

    expected = {
        fact_id: tuple(
            sorted(
                evidence_id
                for evidence_id, item in evidence.evidence.items()
                if fact_id in item.fact_ids
            )
        )
        for fact_id in core.facts
    }
    assert {
        fact_id: fact.related_evidence_ids
        for fact_id, fact in blueprint.facts.items()
    } == expected
    assert all(item.provenance is not None for item in evidence.evidence.values())
    assert {
        item.provenance.evidence_role  # type: ignore[union-attr]
        for item in evidence.evidence.values()
    } == {"method", "motive", "opportunity", "misdirection"}


def test_proof_catalog_contains_only_atomic_culprit_linked_grounded_candidates() -> None:
    payloads = _stage_payloads()
    core = GeneratedCrimeTimelineStage.model_validate(payloads["case_generation_core"])
    catalog = build_proof_support_catalog(core)
    events = {event.id: event for event in core.timeline}
    categories = {
        "method": {"means"},
        "motive": {"motive"},
        "opportunity": {"opportunity", "timeline"},
    }

    assert {candidate.axis for candidate in catalog.candidates.values()} == set(categories)
    for key, candidate in catalog.candidates.items():
        assert key == candidate.candidate_id
        assert candidate.fact_ids
        for fact_id in candidate.fact_ids:
            assert core.facts[fact_id].category.value in categories[candidate.axis]
            assert core.murder.murderer_id in core.facts[fact_id].related_character_ids
            assert fact_id in events[candidate.source_event_id].fact_ids


def test_proof_selection_compiles_exact_catalog_references() -> None:
    payloads = _stage_payloads()
    core = GeneratedCrimeTimelineStage.model_validate(payloads["case_generation_core"])
    catalog = build_proof_support_catalog(core)
    selection = GeneratedProofRouteSelectionStage.model_validate(
        payloads["case_generation_proof_blueprint"]
    )

    blueprint = compile_proof_route_selection(selection, catalog=catalog, core=core)

    for selected_route, compiled_route in zip(selection.routes, blueprint.routes, strict=True):
        for axis in ("method", "motive", "opportunity"):
            selected = getattr(selected_route, axis)
            compiled = getattr(compiled_route, axis)
            candidate = catalog.candidates[selected.support_candidate_id]
            assert compiled.fact_ids == candidate.fact_ids
            assert compiled.source_event_ids == (candidate.source_event_id,)
        assert compiled_route.timeline_fact_ids == compiled_route.opportunity.fact_ids


@pytest.mark.asyncio
async def test_staged_generation_compiles_a_complete_canonical_case() -> None:
    source = load_case("ashwick_sample")
    llm = ScriptedStageLLM(_json_stage_outputs(_stage_payloads()))

    result = await generate_validated_scenario(
        llm,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=TEST_SEED,
        max_attempts=1,
    )

    assert result.case.seed == 901
    assert result.presentation.source == "llm"
    assert len(result.case.evidence) == 8
    assert _roles(llm) == [
        "stage1_semantic_plan",
        "case_generation_proof_blueprint",
        "case_generation_evidence_realization",
        "case_generation_misdirection",
        "case_generation_overlays",
        "case_generation_presentation",
    ]
    assert all(call["json_mode"] is True for call in llm.calls)


@pytest.mark.asyncio
async def test_accepted_stage_observer_receives_exact_private_deltas() -> None:
    source = load_case("ashwick_sample")
    llm = ScriptedStageLLM(_json_stage_outputs(_stage_payloads()))
    accepted: list[dict[str, object]] = []

    await generate_validated_scenario(
        llm,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=TEST_SEED,
        max_attempts=1,
        accepted_stage_observer=lambda record: accepted.append(record),
    )

    assert [record["stage"] for record in accepted] == [
        "case_generation_core",
        "case_generation_proof_blueprint",
        "case_generation_proof_blueprint_compiled",
        "case_generation_evidence_realization",
        "case_generation_misdirection",
        "case_generation_overlays",
        "case_generation_presentation",
    ]
    assert all(len(str(record["stage_fingerprint"])) == 64 for record in accepted)
    assert all(isinstance(record["document"], dict) for record in accepted)


@pytest.mark.asyncio
async def test_accepted_stage_persistence_failure_never_retries_paid_response() -> None:
    source = load_case("ashwick_sample")
    llm = ScriptedStageLLM(_json_stage_outputs(_stage_payloads()))

    def fail_persistence(_record: dict[str, object]) -> None:
        raise OSError("disk unavailable")

    with pytest.raises(GenerationObserverError, match="observer failed"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=3,
            accepted_stage_observer=fail_persistence,
        )

    assert _roles(llm) == ["stage1_semantic_plan"]


@pytest.mark.asyncio
async def test_staged_generation_uses_a_byte_identical_cacheable_prefix() -> None:
    source = load_case("ashwick_sample")
    llm = ScriptedStageLLM(_json_stage_outputs(_stage_payloads()))

    await generate_validated_scenario(
        llm,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=TEST_SEED,
        max_attempts=1,
    )

    prefixes = [
        tuple(message.content for message in call["messages"][:2])
        for call in llm.calls
    ]
    assert len(prefixes) == 6
    assert prefixes[1:] == [prefixes[1]] * 5
    assert prefixes[0] != prefixes[1]
    assert "stage 1 murder semantics" in prefixes[0][0].lower()
    assert "stage schemas" not in prefixes[0][0].lower()


@pytest.mark.asyncio
async def test_malformed_proof_blueprint_stops_before_evidence_spend() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    outputs = _json_stage_outputs(payloads)
    outputs["case_generation_proof_blueprint"] = ["{not json", "{still not json"]
    llm = ScriptedStageLLM(outputs)

    with pytest.raises(GeneratedScenarioError, match="after 2 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=2,
        )

    assert _roles(llm) == [
        "stage1_semantic_plan",
        "case_generation_proof_blueprint",
        "case_generation_proof_blueprint",
    ]


@pytest.mark.asyncio
async def test_proof_repair_keeps_stage1_and_catalog_byte_identical() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    invalid = deepcopy(payloads["case_generation_proof_blueprint"])
    invalid["routes"][0]["method"]["support_candidate_id"] = "unknown"
    outputs = _json_stage_outputs(payloads)
    outputs["case_generation_proof_blueprint"] = [
        json.dumps(invalid),
        json.dumps(payloads["case_generation_proof_blueprint"]),
    ]
    llm = ScriptedStageLLM(outputs)

    result = await generate_validated_scenario(
        llm,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=TEST_SEED,
        max_attempts=2,
    )

    assert result.case.id.startswith("generated_")
    first = json.loads(llm.calls[1]["messages"][2].content)
    repair = json.loads(llm.calls[2]["messages"][2].content)
    assert first["accepted_upstream"] == repair["accepted_upstream"]
    assert "previous attempt was rejected" in repair["repair_feedback"].lower()


@pytest.mark.asyncio
async def test_unknown_proof_candidate_stops_before_realization() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    proof = payloads["case_generation_proof_blueprint"]
    proof["routes"][0]["method"]["support_candidate_id"] = "unknown"  # type: ignore[index]
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "stage1_semantic_plan",
        "case_generation_proof_blueprint",
    ]


@pytest.mark.asyncio
async def test_wrong_axis_proof_candidate_stops_before_realization() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    route = payloads["case_generation_proof_blueprint"]["routes"][0]  # type: ignore[index]
    route["motive"]["support_candidate_id"] = route["method"]["support_candidate_id"]
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=1,
        )

    assert _roles(llm) == ["stage1_semantic_plan", "case_generation_proof_blueprint"]


@pytest.mark.asyncio
async def test_free_form_truth_references_are_forbidden_in_proof_selection() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    method = payloads["case_generation_proof_blueprint"]["routes"][0]["method"]  # type: ignore[index]
    method["fact_ids"] = ["unauthorized"]
    method["source_event_ids"] = ["unauthorized"]
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=1,
        )

    assert _roles(llm) == ["stage1_semantic_plan", "case_generation_proof_blueprint"]


@pytest.mark.asyncio
async def test_stale_proof_catalog_fingerprint_stops_before_realization() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    proof = payloads["case_generation_proof_blueprint"]
    proof["proof_catalog_fingerprint"] = "0" * 64  # type: ignore[index]
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "stage1_semantic_plan",
        "case_generation_proof_blueprint",
    ]


def test_stage1_without_motive_support_stops_before_stage2a_spend() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    core = payloads["case_generation_core"]
    murderer_id = core["murder"]["murderer_id"]  # type: ignore[index]
    for fact in core["facts"].values():  # type: ignore[union-attr]
        if fact["category"] == "motive":
            fact["related_character_ids"] = [
                value for value in fact["related_character_ids"] if value != murderer_id
            ]
    broken = GeneratedCrimeTimelineStage.model_validate(core)
    with pytest.raises(GeneratedScenarioError, match="motive"):
        _validate_core_stage(
            broken,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
        )


@pytest.mark.asyncio
async def test_same_candidate_and_form_cannot_fake_an_independent_causal_channel() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    proof = payloads["case_generation_proof_blueprint"]
    left = proof["routes"][0]["method"]  # type: ignore[index]
    right = proof["routes"][1]["method"]  # type: ignore[index]
    right["required_form"] = left["required_form"]
    right["support_candidate_id"] = left["support_candidate_id"]
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "stage1_semantic_plan",
        "case_generation_proof_blueprint",
    ]


@pytest.mark.asyncio
async def test_realization_cannot_reassign_an_accepted_proof_role() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    realization = payloads["case_generation_evidence_realization"]["realizations"]
    realization["route_1_method"]["route_id"] = "route_2"  # type: ignore[index]
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "stage1_semantic_plan",
        "case_generation_proof_blueprint",
        "case_generation_evidence_realization",
    ]


@pytest.mark.asyncio
async def test_realized_routes_cannot_share_one_discovery_dependency() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    realizations = payloads["case_generation_evidence_realization"]["realizations"]
    realizations["route_2_method"]["discovery"] = deepcopy(
        realizations["route_1_method"]["discovery"]
    )
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "stage1_semantic_plan",
        "case_generation_proof_blueprint",
        "case_generation_evidence_realization",
    ]


@pytest.mark.asyncio
async def test_realization_retry_keeps_the_accepted_proof_blueprint_immutable() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    invalid = deepcopy(payloads["case_generation_evidence_realization"])
    invalid["realizations"]["route_1_method"]["source_event_id"] = "unknown"  # type: ignore[index]
    outputs = _json_stage_outputs(payloads)
    outputs["case_generation_evidence_realization"] = [
        json.dumps(invalid),
        json.dumps(payloads["case_generation_evidence_realization"]),
    ]
    llm = ScriptedStageLLM(outputs)

    result = await generate_validated_scenario(
        llm,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=TEST_SEED,
        max_attempts=2,
    )

    assert result.case.id.startswith("generated_")
    first = json.loads(llm.calls[2]["messages"][2].content)
    repair = json.loads(llm.calls[3]["messages"][2].content)
    assert first["accepted_upstream"]["accepted_proof_contract"] == repair[
        "accepted_upstream"
    ]["accepted_proof_contract"]
    assert "previous attempt was rejected" in repair["repair_feedback"].lower()


@pytest.mark.asyncio
async def test_misdirection_cannot_target_culprit_or_rewrite_true_evidence() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    invalid = deepcopy(payloads["case_generation_misdirection"])
    invalid["misdirection"]["misdirection_1"]["implicates_character_ids"] = [  # type: ignore[index]
        source.murder.murderer_id
    ]
    invalid["realizations"] = {}
    outputs = _json_stage_outputs(payloads)
    outputs["case_generation_misdirection"] = [json.dumps(invalid)]
    llm = ScriptedStageLLM(outputs)

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=1,
        )

    assert _roles(llm)[-1] == "case_generation_misdirection"
    assert "case_generation_overlays" not in _roles(llm)


@pytest.mark.asyncio
async def test_overlay_requires_the_exact_selected_cast_before_presentation() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    overlays = payloads["case_generation_overlays"]["overlays"]
    overlays.pop(source.character_ids[-1])  # type: ignore[union-attr]
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=TEST_SEED,
            max_attempts=1,
        )

    assert _roles(llm)[-1] == "case_generation_overlays"
    assert "case_generation_presentation" not in _roles(llm)


@pytest.mark.asyncio
async def test_public_spoiler_retries_only_presentation_after_truth_admission() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    invalid = deepcopy(payloads["case_generation_presentation"])
    invalid["presentation"]["public_opening"] = (  # type: ignore[index]
        "The murderer and the weapon are already obvious."
    )
    outputs = _json_stage_outputs(payloads)
    outputs["case_generation_presentation"] = [
        json.dumps(invalid),
        json.dumps(payloads["case_generation_presentation"]),
    ]
    llm = ScriptedStageLLM(outputs)

    result = await generate_validated_scenario(
        llm,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=TEST_SEED,
        max_attempts=2,
    )

    assert result.case.id.startswith("generated_")
    assert _roles(llm)[-2:] == [
        "case_generation_presentation",
        "case_generation_presentation",
    ]
    assert "previous attempt was rejected" in llm.calls[-1]["messages"][2].content.lower()
