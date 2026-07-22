"""Falsifiable tests for the semantic Stage 1 and host compiler boundary."""

from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from game.case_generation import (
    GeneratedCrimeTimelineStage,
    _validate_core_stage,
    build_proof_support_catalog,
)
from game.content import load_case, load_location
from game.models import DeathMode
from game.stage1_semantic import (
    Stage1SemanticError,
    Stage1SemanticPatch,
    Stage1SemanticPlan,
    apply_stage1_semantic_patch,
    build_stage1_alias_map,
    build_stage1_semantic_messages,
    compile_stage1_semantic_plan,
    compiled_causal_chain_issues,
    content_fingerprint,
    generate_stage1_boundary,
    role_assignment_fingerprint,
    select_stage1_roles,
    validate_stage1_semantic_plan,
)


def _fixture(*, seed: int = 2026072201, death_mode: DeathMode = DeathMode.HOMICIDE):
    source = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    roles = select_stage1_roles(
        character_ids=source.character_ids,
        seed=seed,
        death_mode=death_mode,
    )
    aliases = build_stage1_alias_map(source.character_ids, location)
    messages = build_stage1_semantic_messages(
        character_ids=source.character_ids,
        location=location,
        assignment=roles,
        aliases=aliases,
    )
    payload = json.loads(messages[1].content)
    plan = Stage1SemanticPlan.model_validate(payload["valid_example"])
    return source, location, roles, aliases, plan, messages


def _delayed_plan(plan: Stage1SemanticPlan) -> Stage1SemanticPlan:
    document = plan.model_dump(mode="json")
    fixed = document["fixed_roles"]
    victim = fixed["victim_ref"]
    responsible = fixed["responsible_actor_ref"]
    discoverer = fixed["discoverer_ref"]
    room = document["means"]["origin_room_ref"]
    document["means"]["delivery_mode"] = "delayed"
    document["means"]["causal_mechanism"] = (
        "A prepared delayed dose is encountered later and causes death after the actor leaves."
    )
    document["method"] = "A delayed dose causes fatal collapse after delivery."
    document["causal_beats"] = [
        {
            "key": "prepare",
            "order": 1,
            "kind": "preparation",
            "actor_refs": [responsible],
            "room_ref": room,
            "earliest_minute": 20,
            "latest_minute": 30,
            "summary": "The responsible actor prepares and places a delayed dose.",
            "depends_on_keys": [],
            "involves_means": True,
            "victim_encounters_means": False,
            "requires_responsible_victim_colocation": False,
        },
        {
            "key": "exposure",
            "order": 2,
            "kind": "exposure",
            "actor_refs": [victim],
            "room_ref": room,
            "earliest_minute": 50,
            "latest_minute": 60,
            "summary": "The victim unknowingly encounters the previously delivered dose.",
            "depends_on_keys": ["prepare"],
            "involves_means": True,
            "victim_encounters_means": True,
            "requires_responsible_victim_colocation": False,
        },
        {
            "key": "death",
            "order": 3,
            "kind": "death",
            "actor_refs": [victim],
            "room_ref": room,
            "earliest_minute": 75,
            "latest_minute": 85,
            "summary": "The delayed mechanism causes the victim's death.",
            "depends_on_keys": ["exposure"],
            "involves_means": True,
            "victim_encounters_means": True,
            "requires_responsible_victim_colocation": False,
        },
        {
            "key": "discover",
            "order": 4,
            "kind": "discovery",
            "actor_refs": [discoverer, victim],
            "room_ref": room,
            "earliest_minute": 100,
            "latest_minute": 110,
            "summary": "The locked discoverer finds the victim and raises the alarm.",
            "depends_on_keys": ["death"],
            "involves_means": False,
            "victim_encounters_means": False,
            "requires_responsible_victim_colocation": False,
        },
    ]
    document["discovery"]["beat_key"] = "discover"
    document["support_anchors"] = [
        {
            "key": "method_anchor",
            "axis": "method",
            "beat_keys": ["prepare"],
            "actor_ref": responsible,
            "statement": "The actor prepared and delivered the delayed means.",
            "conclusion": "The prepared dose explains the fatal mechanism.",
            "causal_link": "Preparation causally precedes exposure and death.",
        },
        {
            "key": "motive_anchor",
            "axis": "motive",
            "beat_keys": ["prepare"],
            "actor_ref": responsible,
            "statement": "The preparation was motivated by threatened exposure.",
            "conclusion": "The responsible actor had a concrete motive.",
            "causal_link": "The actor's deliberate preparation enacts the stated motive.",
        },
        {
            "key": "opportunity_anchor",
            "axis": "opportunity",
            "beat_keys": ["prepare"],
            "actor_ref": responsible,
            "statement": "The actor had private access before the victim's exposure.",
            "conclusion": "The actor had opportunity without attending the death.",
            "causal_link": "The access window permits delivery before exposure.",
        },
    ]
    return Stage1SemanticPlan.model_validate(document)


def test_seeded_roles_are_deterministic_homicide_roles() -> None:
    source = load_case("ashwick_sample")
    first = select_stage1_roles(character_ids=source.character_ids, seed=77)
    second = select_stage1_roles(character_ids=source.character_ids, seed=77)

    assert first == second
    assert first.death_mode == DeathMode.HOMICIDE
    assert first.victim_id != first.responsible_actor_id
    assert first.discoverer_id != first.victim_id
    assert len(role_assignment_fingerprint(first)) == 64


def test_valid_semantic_plan_compiles_to_existing_stage2_boundary() -> None:
    source, location, roles, aliases, plan, _ = _fixture()

    assert validate_stage1_semantic_plan(
        plan,
        assignment=roles,
        aliases=aliases,
        location=location,
    ).is_valid
    document = compile_stage1_semantic_plan(
        plan,
        assignment=roles,
        aliases=aliases,
        location=location,
    )
    core = GeneratedCrimeTimelineStage.model_validate(document)
    _validate_core_stage(core, character_ids=source.character_ids, location=location)
    catalog = build_proof_support_catalog(core)

    assert core.stage1_contract_version == "semantic-v1"
    assert core.murder.victim_id == roles.victim_id
    assert core.murder.murderer_id == roles.responsible_actor_id
    assert core.opening.discoverer_id == roles.discoverer_id
    assert core.murder.weapon_id in core.case_means
    assert core.murder.weapon_id not in location.potential_weapons
    assert {candidate.axis for candidate in catalog.candidates.values()} == {
        "method",
        "motive",
        "opportunity",
    }


def test_model_cannot_emit_invalid_fact_category_or_canonical_ids() -> None:
    _, _, _, _, plan, messages = _fixture()
    prompt = messages[1].content
    compiled = compile_stage1_semantic_plan(
        plan,
        assignment=_fixture()[2],
        aliases=_fixture()[3],
        location=_fixture()[1],
    )

    assert "FactCategory" not in prompt
    assert "case_generation_proof_blueprint" not in prompt
    assert "related_evidence_ids" not in prompt
    assert {fact["category"] for fact in compiled["facts"].values()} <= {
        "means",
        "motive",
        "opportunity",
        "timeline",
        "secret",
    }


def test_delayed_mechanism_does_not_require_responsible_actor_at_death() -> None:
    source, location, roles, aliases, direct, _ = _fixture()
    plan = _delayed_plan(direct)
    report = validate_stage1_semantic_plan(
        plan,
        assignment=roles,
        aliases=aliases,
        location=location,
    )
    assert report.is_valid, report.issues
    core = GeneratedCrimeTimelineStage.model_validate(
        compile_stage1_semantic_plan(
            plan,
            assignment=roles,
            aliases=aliases,
            location=location,
        )
    )
    death = next(event for event in core.timeline if event.causal_role.value == "death")

    assert roles.responsible_actor_id not in death.actor_ids
    assert not compiled_causal_chain_issues(
        murder=core.murder,
        timeline=core.timeline,
        case_means=core.case_means,
        opening=core.opening,
        character_ids=source.character_ids,
        location=location,
    )


def test_direct_attack_without_marked_colocation_is_rejected() -> None:
    _, location, roles, aliases, plan, _ = _fixture()
    document = plan.model_dump(mode="json")
    document["causal_beats"][1]["requires_responsible_victim_colocation"] = False
    document["causal_beats"][2]["requires_responsible_victim_colocation"] = False
    broken = Stage1SemanticPlan.model_validate(document)

    codes = {
        issue.code
        for issue in validate_stage1_semantic_plan(
            broken,
            assignment=roles,
            aliases=aliases,
            location=location,
        ).issues
    }
    assert "direct_attack_colocation_unmarked" in codes
    assert "direct_attack_missing" in codes


def test_suicide_compatible_representation_does_not_require_two_actors() -> None:
    _, location, roles, aliases, direct, _ = _fixture(
        seed=2026072202,
        death_mode=DeathMode.SUICIDE,
    )
    plan = _delayed_plan(direct)
    document = plan.model_dump(mode="json")
    document["means"]["delivery_mode"] = "self_administered"
    plan = Stage1SemanticPlan.model_validate(document)
    report = validate_stage1_semantic_plan(
        plan,
        assignment=roles,
        aliases=aliases,
        location=location,
    )
    assert roles.victim_id == roles.responsible_actor_id
    assert report.is_valid, report.issues
    core = GeneratedCrimeTimelineStage.model_validate(
        compile_stage1_semantic_plan(
            plan,
            assignment=roles,
            aliases=aliases,
            location=location,
        )
    )
    assert core.murder.death_mode == DeathMode.SUICIDE
    assert core.murder.responsible_actor_id == core.murder.victim_id


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("locked_roles", "locked_role_mismatch"),
        ("survivor_map", "invalid_survivor_map"),
        ("support_link", "support_missing_responsible_link"),
        ("missing_axis", "missing_motive_support"),
        ("impossible_travel", "impossible_actor_travel"),
    ],
)
def test_captured_failure_mutations_are_rejected(mutation: str, expected_code: str) -> None:
    _, location, roles, aliases, plan, _ = _fixture()
    document = plan.model_dump(mode="json")
    if mutation == "locked_roles":
        document["fixed_roles"]["victim_ref"] = document["fixed_roles"]["discoverer_ref"]
    elif mutation == "survivor_map":
        document["survivor_placements"] = document["survivor_placements"][:-1]
    elif mutation == "support_link":
        document["support_anchors"][0]["beat_keys"] = ["death"]
    elif mutation == "missing_axis":
        document["support_anchors"][1]["axis"] = "method"
    else:
        alternate = next(
            ref
            for ref in aliases.alias_to_room
            if ref != document["causal_beats"][1]["room_ref"]
        )
        document["causal_beats"][2]["room_ref"] = alternate
        document["causal_beats"][2]["earliest_minute"] = 55
        document["causal_beats"][2]["latest_minute"] = 55
    broken = Stage1SemanticPlan.model_validate(document)
    codes = {
        issue.code
        for issue in validate_stage1_semantic_plan(
            broken,
            assignment=roles,
            aliases=aliases,
            location=location,
        ).issues
    }
    assert expected_code in codes


def test_patch_rejects_locked_unauthorized_and_stale_changes() -> None:
    _, _, _, _, plan, _ = _fixture()
    base = content_fingerprint(plan.model_dump(mode="json"))
    locked = Stage1SemanticPatch.model_validate(
        {
            "base_fingerprint": base,
            "operations": [
                {"op": "replace", "path": "/fixed_roles/victim_ref", "value": "c8"}
            ],
        }
    )
    with pytest.raises(Stage1SemanticError, match="locked"):
        apply_stage1_semantic_patch(
            plan,
            locked,
            allowed_paths=("/fixed_roles/victim_ref",),
        )
    unauthorized = Stage1SemanticPatch.model_validate(
        {
            "base_fingerprint": base,
            "operations": [{"op": "replace", "path": "/title", "value": "Other"}],
        }
    )
    with pytest.raises(Stage1SemanticError, match="unauthorized"):
        apply_stage1_semantic_patch(
            plan,
            unauthorized,
            allowed_paths=("/opportunity",),
        )
    stale = Stage1SemanticPatch.model_validate(
        {
            "base_fingerprint": "0" * 64,
            "operations": [{"op": "replace", "path": "/title", "value": "Other"}],
        }
    )
    with pytest.raises(Stage1SemanticError, match="stale"):
        apply_stage1_semantic_patch(plan, stale, allowed_paths=("/title",))


class ScriptedSemanticLLM:
    def __init__(self, outputs: dict[str, list[SimpleNamespace]]) -> None:
        self.outputs = {key: list(value) for key, value in outputs.items()}
        self.calls: list[str] = []

    async def generate(self, messages, **kwargs):
        role = kwargs["task_role"]
        self.calls.append(role)
        return self.outputs[role].pop(0)


def _response(content: str, *, finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        finish_reason=finish_reason,
        prompt_tokens=10,
        completion_tokens=20,
        reasoning_tokens=5,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "finish_reason", "category"),
    [
        ("{", "stop", "malformed_json"),
        ("{}", "length", "truncated_output"),
        ("", "stop", "empty_response"),
        (json.dumps({"schema_version": 1}), "stop", "schema_invalid_json"),
    ],
)
async def test_generation_classifies_invalid_outputs_separately(
    content: str,
    finish_reason: str,
    category: str,
) -> None:
    source, location, roles, _, _, _ = _fixture()
    observed: list[dict[str, object]] = []
    llm = ScriptedSemanticLLM(
        {"stage1_semantic_plan": [_response(content, finish_reason=finish_reason)]}
    )

    with pytest.raises(Stage1SemanticError):
        await generate_stage1_boundary(
            llm,
            character_ids=source.character_ids,
            location=location,
            seed=2026072201,
            assignment=roles,
            max_initial_attempts=1,
            max_delta_repairs=0,
            attempt_observer=observed.append,
        )
    assert observed[0]["failure_category"] == category


@pytest.mark.asyncio
async def test_fingerprinted_delta_repair_changes_only_declared_field() -> None:
    source, location, roles, _, plan, _ = _fixture()
    broken_document = plan.model_dump(mode="json")
    correct_placements = deepcopy(broken_document["survivor_placements"])
    broken_document["survivor_placements"] = broken_document["survivor_placements"][:-1]
    broken = Stage1SemanticPlan.model_validate(broken_document)
    patch = {
        "schema_version": 1,
        "base_fingerprint": content_fingerprint(broken.model_dump(mode="json")),
        "operations": [
            {
                "op": "replace",
                "path": "/survivor_placements",
                "value": correct_placements,
            }
        ],
    }
    observed: list[dict[str, object]] = []
    llm = ScriptedSemanticLLM(
        {
            "stage1_semantic_plan": [_response(json.dumps(broken_document))],
            "stage1_semantic_delta_repair": [_response(json.dumps(patch))],
        }
    )

    result = await generate_stage1_boundary(
        llm,
        character_ids=source.character_ids,
        location=location,
        seed=2026072201,
        assignment=roles,
        max_initial_attempts=1,
        max_delta_repairs=1,
        attempt_observer=observed.append,
    )

    assert result.semantic_plan.fixed_roles == broken.fixed_roles
    assert result.semantic_plan.survivor_placements == plan.survivor_placements
    assert llm.calls == ["stage1_semantic_plan", "stage1_semantic_delta_repair"]
    assert observed[-1]["result"] == "admitted"
