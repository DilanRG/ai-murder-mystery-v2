"""Falsifiable provider-free tests for Revision 9 staged canonical generation."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from conftest import generated_stage_payloads, make_dummy_generated_document

from game.case_generation import (
    GeneratedCrimeTimelineStage,
    GeneratedEvidenceRealizationStage,
    GeneratedMisdirectionConnectiveStage,
    GeneratedOverlayKnowledgeStage,
    GeneratedProofRouteBlueprintStage,
    GeneratedScenarioError,
    assemble_evidence_solution_stage,
    assemble_generated_case_blueprint,
    generate_validated_scenario,
)
from game.content import load_case, load_location


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
    return generated_stage_payloads(make_dummy_generated_document())


def _json_stage_outputs(
    payloads: dict[str, dict[str, object]],
) -> dict[str, list[str | Exception]]:
    return {role: [json.dumps(payload)] for role, payload in payloads.items()}


def _roles(llm: ScriptedStageLLM) -> list[str]:
    return [str(call["task_role"]) for call in llm.calls]


def _parse_truth_stages():
    payloads = _stage_payloads()
    core = GeneratedCrimeTimelineStage.model_validate(payloads["case_generation_core"])
    proof = GeneratedProofRouteBlueprintStage.model_validate(
        payloads["case_generation_proof_blueprint"]
    )
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


@pytest.mark.asyncio
async def test_staged_generation_compiles_a_complete_canonical_case() -> None:
    source = load_case("ashwick_sample")
    llm = ScriptedStageLLM(_json_stage_outputs(_stage_payloads()))

    result = await generate_validated_scenario(
        llm,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=901,
        max_attempts=1,
    )

    assert result.case.seed == 901
    assert result.presentation.source == "llm"
    assert len(result.case.evidence) == 8
    assert _roles(llm) == [
        "case_generation_core",
        "case_generation_proof_blueprint",
        "case_generation_evidence_realization",
        "case_generation_misdirection",
        "case_generation_overlays",
        "case_generation_presentation",
    ]
    assert all(call["json_mode"] is True for call in llm.calls)


@pytest.mark.asyncio
async def test_staged_generation_uses_a_byte_identical_cacheable_prefix() -> None:
    source = load_case("ashwick_sample")
    llm = ScriptedStageLLM(_json_stage_outputs(_stage_payloads()))

    await generate_validated_scenario(
        llm,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=902,
        max_attempts=1,
    )

    prefixes = [
        tuple(message.content for message in call["messages"][:2])
        for call in llm.calls
    ]
    assert len(prefixes) == 6
    assert prefixes[1:] == [prefixes[0]] * 5


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
            seed=903,
            max_attempts=2,
        )

    assert _roles(llm) == [
        "case_generation_core",
        "case_generation_proof_blueprint",
        "case_generation_proof_blueprint",
    ]


@pytest.mark.asyncio
async def test_ungrounded_proof_claim_stops_before_realization() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    proof = payloads["case_generation_proof_blueprint"]
    proof["routes"][0]["method"]["source_event_ids"] = ["timeline_meeting"]  # type: ignore[index]
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=904,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "case_generation_core",
        "case_generation_proof_blueprint",
    ]


@pytest.mark.asyncio
async def test_each_proof_source_event_must_independently_ground_its_claim() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    proof = payloads["case_generation_proof_blueprint"]
    claim = proof["routes"][0]["method"]  # type: ignore[index]
    unrelated_event_id = next(
        event["id"]
        for event in payloads["case_generation_core"]["timeline"]
        if not set(claim["fact_ids"]) <= set(event["fact_ids"])
    )
    claim["source_event_ids"].append(unrelated_event_id)
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=9041,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "case_generation_core",
        "case_generation_proof_blueprint",
    ]


@pytest.mark.asyncio
async def test_decorative_event_id_cannot_fake_an_independent_causal_channel() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    core = payloads["case_generation_core"]
    proof = payloads["case_generation_proof_blueprint"]
    left = proof["routes"][0]["method"]  # type: ignore[index]
    right = proof["routes"][1]["method"]  # type: ignore[index]
    source_event = next(
        event
        for event in core["timeline"]
        if event["id"] == left["source_event_ids"][0]
    )
    decorative = deepcopy(source_event)
    decorative["id"] = "timeline_decorative_independence_claim"
    decorative["fact_ids"] = list(
        dict.fromkeys([*decorative["fact_ids"], *right["fact_ids"]])
    )
    core["timeline"].append(decorative)
    core["timeline"].sort(key=lambda event: (event["minute"], event["id"]))
    right["required_form"] = left["required_form"]
    right["source_event_ids"] = [decorative["id"]]
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=9042,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "case_generation_core",
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
            seed=905,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "case_generation_core",
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
            seed=9051,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "case_generation_core",
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
        seed=906,
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
            seed=907,
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
            seed=908,
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
        seed=909,
        max_attempts=2,
    )

    assert result.case.id.startswith("generated_")
    assert _roles(llm)[-2:] == [
        "case_generation_presentation",
        "case_generation_presentation",
    ]
    assert "previous attempt was rejected" in llm.calls[-1]["messages"][2].content.lower()
