"""Generated-case admission tests using authored dummy output, never OpenRouter."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from game.case_generation import (
    GeneratedScenarioError,
    build_generation_context,
    compile_generated_scenario,
    generate_validated_scenario,
)
from game.actions import (
    AccuseIntent,
    AdvanceOpeningIntent,
    ExamineBodyIntent,
    MoveIntent,
    SearchIntent,
)
from game.content import load_case, load_location
from game.engine import GameEngine
from game.story_director import fallback_story_presentation
from game.validator import validate_case


class DummyScenarioLLM:
    def __init__(self, outputs: list[str | Exception]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, object]] = []

    async def generate(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(content=output)


def _dummy_document() -> dict[str, object]:
    """Treat the validated authored sample as if a provider had emitted it."""

    case = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    case_data = case.model_dump(mode="json")
    retained_evidence_ids = {
        "ev_library_poker",
        "ev_fireplace_trace",
        "ev_medical_assessment",
        "ev_library_clock",
        "ev_edgar_cuff_fibre",
        "ev_vivienne_memo",
        "ev_sabrina_earring",
        "ev_captain_letter",
        "ev_port_rag",
        "ev_sabrina_captain_alibi",
    }
    case_data["evidence"] = {
        evidence_id: evidence
        for evidence_id, evidence in case_data["evidence"].items()
        if evidence_id in retained_evidence_ids
    }
    for fact in case_data["facts"].values():
        fact["related_evidence_ids"] = [
            evidence_id
            for evidence_id in fact["related_evidence_ids"]
            if evidence_id in retained_evidence_ids
        ]
    for overlay in case_data["overlays"].values():
        overlay["supporting_evidence_ids"] = [
            evidence_id
            for evidence_id in overlay["supporting_evidence_ids"]
            if evidence_id in retained_evidence_ids
        ]
    case_data["solution"]["method_evidence_ids"] = [
        "ev_library_poker",
        "ev_fireplace_trace",
        "ev_medical_assessment",
    ]
    case_data["solution"]["motive_evidence_ids"] = ["ev_vivienne_memo"]
    case_data["solution"]["opportunity_evidence_ids"] = [
        "ev_library_clock",
        "ev_edgar_cuff_fibre",
    ]
    opening = dict(case_data["opening"])
    opening.pop("assembly_room_id")
    presentation = fallback_story_presentation(case, location).model_dump(mode="json")
    for host_field in ("schema_version", "base_case_fingerprint", "source"):
        presentation.pop(host_field)
    return {
        "schema_version": 1,
        "case": {
            "schema_version": 1,
            "title": case.title,
            "investigation_start_minute": case.investigation_start_minute,
            "murder": case_data["murder"],
            "facts": case_data["facts"],
            "timeline": case_data["timeline"],
            "overlays": case_data["overlays"],
            "evidence": case_data["evidence"],
            "opening": opening,
            "solution": case_data["solution"],
        },
        "presentation": presentation,
    }


def test_dummy_generated_document_compiles_only_after_full_validation() -> None:
    source = load_case("ashwick_sample")
    location = load_location("ashwick_manor")

    result = compile_generated_scenario(
        _dummy_document(),
        character_ids=source.character_ids,
        location=location,
        seed=84,
    )

    assert result.case.id.startswith("generated_")
    assert result.case.seed == 84
    assert result.case.location_package_id == location.id
    assert result.case.character_ids == source.character_ids
    assert result.case.initial_player_room_id == location.assembly_room_id
    assert result.case.opening.assembly_room_id == location.assembly_room_id
    assert result.presentation.source == "llm"
    assert result.presentation.base_case_fingerprint
    assert validate_case(result.case, location).is_valid
    assert 6 <= len(result.case.evidence) <= 10
    assert 2 <= sum(item.is_red_herring for item in result.case.evidence.values()) <= 4


def test_dummy_generated_case_can_be_played_to_a_supported_solution() -> None:
    source = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    generated = compile_generated_scenario(
        _dummy_document(),
        character_ids=source.character_ids,
        location=location,
        seed=84,
    )
    engine = GameEngine(generated.case, location)

    engine.apply(AdvanceOpeningIntent())
    engine.apply(MoveIntent(room_id="library"))
    engine.apply(ExamineBodyIntent())
    engine.apply(SearchIntent(object_id="library_desk"))
    engine.apply(SearchIntent(object_id="library_desk"))
    known_facts = {fact.id: fact.statement for fact in engine.view().known_facts}
    result = engine.apply(
        AccuseIntent(
            character_id=generated.case.murder.murderer_id,
            evidence_ids=sorted(
                engine.runtime.player_knowledge.discovered_evidence_ids
            ),
            method=known_facts["fact_murder_method"],
            motive=known_facts["fact_financial_exposure"],
            timeline=known_facts["fact_murder_time"],
        )
    )

    assert result.game.result is not None
    assert result.game.result.solved
    assert result.game.result.support_score == 3


def test_generated_document_rejects_too_many_clues_or_too_few_red_herrings() -> None:
    source = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    too_many = _dummy_document()
    template = deepcopy(too_many["case"]["evidence"]["ev_port_rag"])  # type: ignore[index]
    for suffix in ("extra_one", "extra_two"):
        duplicate = deepcopy(template)
        duplicate["id"] = suffix
        too_many["case"]["evidence"][suffix] = duplicate  # type: ignore[index]

    with pytest.raises(GeneratedScenarioError, match="at most 10"):
        compile_generated_scenario(
            too_many,
            character_ids=source.character_ids,
            location=location,
            seed=1,
        )

    too_few_red_herrings = _dummy_document()
    for evidence in too_few_red_herrings["case"]["evidence"].values():  # type: ignore[index]
        evidence["is_red_herring"] = False
        evidence["red_herring_explanation"] = ""
    with pytest.raises(GeneratedScenarioError, match="2 to 4 red herrings"):
        compile_generated_scenario(
            too_few_red_herrings,
            character_ids=source.character_ids,
            location=location,
            seed=1,
        )


def test_generated_document_cannot_reference_a_character_outside_selected_cast() -> None:
    source = load_case("ashwick_sample")
    document = _dummy_document()
    document["case"]["murder"]["murderer_id"] = "not_selected"  # type: ignore[index]

    with pytest.raises(GeneratedScenarioError, match="invalid generated case"):
        compile_generated_scenario(
            document,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=1,
        )


def test_generation_context_contains_selected_cards_and_location_but_no_card_prompts() -> None:
    source = load_case("ashwick_sample")
    location = load_location("ashwick_manor")

    context = build_generation_context(
        character_ids=source.character_ids,
        location=location,
        seed=7,
        difficulty="normal",
    )
    serialized = json.dumps(context)

    assert set(context["selected_character_ids"]) == set(source.character_ids)
    assert context["location"]["id"] == location.id
    assert set(context["location"]["rooms"]) == set(location.rooms)
    for character_id in source.character_ids:
        assert character_id in serialized
    for forbidden in ("system_prompt", "post_history_instructions", "character_book"):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_invalid_generation_retries_with_feedback_then_accepts_dummy_case() -> None:
    source = load_case("ashwick_sample")
    llm = DummyScenarioLLM(["{not json", json.dumps(_dummy_document())])

    result = await generate_validated_scenario(
        llm,
        character_ids=source.character_ids,
        location=load_location("ashwick_manor"),
        seed=295,
        max_attempts=2,
    )

    assert result.case.seed == 295
    assert len(llm.calls) == 2
    assert "previous attempt was rejected" in llm.calls[1]["messages"][1].content.lower()  # type: ignore[index]
    assert "inert story data" in llm.calls[0]["messages"][0].content.lower()  # type: ignore[index]
    assert all(call["json_mode"] is True for call in llm.calls)


@pytest.mark.asyncio
async def test_generation_fails_closed_without_authored_fallback() -> None:
    source = load_case("ashwick_sample")
    llm = DummyScenarioLLM(["{}", RuntimeError("provider unavailable")])

    with pytest.raises(GeneratedScenarioError, match="after 2 attempts"):
        await generate_validated_scenario(
            llm,
            character_ids=source.character_ids,
            location=load_location("ashwick_manor"),
            seed=6,
            max_attempts=2,
        )

    assert len(llm.calls) == 2
