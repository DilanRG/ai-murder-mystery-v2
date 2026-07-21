"""Adversarial, provider-free coverage for staged canonical generation.

These tests deliberately use the authored projection only as inert fixture data.
They exercise the staged proposal boundary: a malformed or incompatible proposal
must stop before it can become canonical truth, and accepted stage inputs must
still pass the normal complete-document compiler.
"""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from conftest import make_dummy_generated_document

from game.case_generation import (
    GeneratedCrimeTimelineStage,
    GeneratedEvidenceSolutionStage,
    GeneratedOverlayKnowledgeStage,
    GeneratedScenarioError,
    assemble_generated_case_blueprint,
    generate_validated_scenario,
)
from game.content import load_case, load_location


class ScriptedStageLLM:
    """A deterministic staged provider that records every chargeable request."""

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
    """Split a valid full document exactly along the staged proposal seams."""

    document = make_dummy_generated_document()
    case = document["case"]
    assert isinstance(case, dict)
    return {
        "case_generation_core": {
            "schema_version": 1,
            **{
                key: deepcopy(case[key])
                for key in (
                    "title",
                    "investigation_start_minute",
                    "murder",
                    "facts",
                    "timeline",
                    "opening",
                )
            },
        },
        "case_generation_evidence": {
            "schema_version": 1,
            **{
                key: deepcopy(case[key])
                for key in ("evidence", "solution")
            },
        },
        "case_generation_overlays": {
            "schema_version": 1,
            "overlays": deepcopy(case["overlays"]),
        },
        "case_generation_presentation": {
            "schema_version": 1,
            "presentation": deepcopy(document["presentation"]),
        },
    }


def _json_stage_outputs(
    payloads: dict[str, dict[str, object]],
) -> dict[str, list[str | Exception]]:
    return {role: [json.dumps(payload)] for role, payload in payloads.items()}


def _roles(llm: ScriptedStageLLM) -> list[str]:
    return [str(call["task_role"]) for call in llm.calls]


def test_stage_assembly_derives_fact_evidence_links_from_evidence_once() -> None:
    payloads = _stage_payloads()
    crime = GeneratedCrimeTimelineStage.model_validate(
        payloads["case_generation_core"]
    )
    evidence = GeneratedEvidenceSolutionStage.model_validate(
        payloads["case_generation_evidence"]
    )
    overlays = GeneratedOverlayKnowledgeStage.model_validate(
        payloads["case_generation_overlays"]
    )

    blueprint = assemble_generated_case_blueprint(crime, evidence, overlays)

    expected = {
        fact_id: tuple(
            sorted(
                evidence_id
                for evidence_id, item in evidence.evidence.items()
                if fact_id in item.fact_ids
            )
        )
        for fact_id in crime.facts
    }
    assert {
        fact_id: fact.related_evidence_ids
        for fact_id, fact in blueprint.facts.items()
    } == expected


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
    assert _roles(llm) == [
        "case_generation_core",
        "case_generation_evidence",
        "case_generation_overlays",
        "case_generation_presentation",
    ]
    assert all(call["json_mode"] is True for call in llm.calls)
    assert all(int(call["max_tokens"]) > 0 for call in llm.calls)


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
    assert len(prefixes) == 4
    assert prefixes[1:] == [prefixes[0]] * 3


@pytest.mark.asyncio
async def test_malformed_evidence_stage_stops_downstream_and_never_admits_partial_truth() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    outputs = _json_stage_outputs(payloads)
    outputs["case_generation_evidence"] = ["{not json", "{still not json"]
    llm = ScriptedStageLLM(outputs)

    with pytest.raises(GeneratedScenarioError, match="after 2 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=903,
            max_attempts=2,
        )

    # Core was accepted once, but no later-stage proposal may run and no
    # partially merged document is returned from a failure path.
    assert _roles(llm) == [
        "case_generation_core",
        "case_generation_evidence",
        "case_generation_evidence",
    ]


@pytest.mark.asyncio
async def test_cross_axis_evidence_route_is_rejected_before_overlay_spend() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    solution = payloads["case_generation_evidence"]["solution"]
    assert isinstance(solution, dict)
    routes = solution["evidence_routes"]
    assert isinstance(routes, list)
    routes[0]["method_evidence_ids"] = deepcopy(routes[0]["motive_evidence_ids"])
    llm = ScriptedStageLLM(_json_stage_outputs(payloads))

    with pytest.raises(GeneratedScenarioError, match="after 1 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=907,
            max_attempts=1,
        )

    assert _roles(llm) == [
        "case_generation_core",
        "case_generation_evidence",
    ]


@pytest.mark.asyncio
async def test_overlay_stage_requires_the_exact_selected_cast_before_presentation() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    overlays = payloads["case_generation_overlays"]["overlays"]
    assert isinstance(overlays, dict)
    overlays.pop(source.character_ids[-1])
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
        "case_generation_evidence",
        "case_generation_overlays",
    ]


@pytest.mark.asyncio
async def test_only_the_rejected_stage_retries_with_feedback_and_retry_is_bounded() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    outputs = _json_stage_outputs(payloads)
    outputs["case_generation_evidence"] = [
        json.dumps({"schema_version": 1, "facts": {}}),
        json.dumps(payloads["case_generation_evidence"]),
    ]
    llm = ScriptedStageLLM(outputs)

    result = await generate_validated_scenario(
        llm,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=905,
        max_attempts=2,
    )

    assert result.case.id.startswith("generated_")
    assert _roles(llm) == [
        "case_generation_core",
        "case_generation_evidence",
        "case_generation_evidence",
        "case_generation_overlays",
        "case_generation_presentation",
    ]
    evidence_repair_messages = llm.calls[2]["messages"]
    assert any(
        "previous attempt was rejected" in message.content.lower()
        for message in evidence_repair_messages[2:]
    )
    # Repair instructions are appended after the cache-stable first two messages.
    assert tuple(message.content for message in llm.calls[1]["messages"][:2]) == tuple(
        message.content for message in llm.calls[2]["messages"][:2]
    )


@pytest.mark.asyncio
async def test_public_spoiler_retries_only_presentation_after_truth_admission() -> None:
    source = load_case("ashwick_sample")
    payloads = _stage_payloads()
    invalid_presentation = deepcopy(payloads["case_generation_presentation"])
    invalid_presentation["presentation"]["public_opening"] = (  # type: ignore[index]
        "The murderer and the weapon are already obvious."
    )
    outputs = _json_stage_outputs(payloads)
    outputs["case_generation_presentation"] = [
        json.dumps(invalid_presentation),
        json.dumps(payloads["case_generation_presentation"]),
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
    assert _roles(llm) == [
        "case_generation_core",
        "case_generation_evidence",
        "case_generation_overlays",
        "case_generation_presentation",
        "case_generation_presentation",
    ]
    assert "previous attempt was rejected" in llm.calls[4]["messages"][2].content.lower()  # type: ignore[index]
