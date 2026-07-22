"""Falsifiable tests for the Stage 2 semantic evidence compiler boundary."""

from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from game.case_generation import GeneratedCrimeTimelineStage
from game.content import load_case, load_location
from game.models import EvidenceKind, LocationPackage
from game.stage1_semantic import content_fingerprint
from game.stage2_semantic import (
    CompiledStage2A,
    Stage2ASemanticCandidate,
    Stage2BRealizationProposal,
    Stage2BSemanticCandidate,
    Stage2CRedHerringProposal,
    Stage2CSemanticCandidate,
    Stage2PatchOperation,
    Stage2SemanticError,
    Stage2SemanticPatch,
    _generate_semantic_stage,
    apply_stage2_semantic_patch,
    assemble_stage2_artifact,
    build_discovery_affordance_catalogue,
    build_secondary_secret_catalogue,
    build_stage2_proof_support_catalogue,
    build_stage2a_messages,
    build_stage2b_messages,
    build_stage2c_messages,
    compile_stage2a_candidate,
    compile_stage2b_candidate,
    compile_stage2c_candidate,
    compiled_stage2a_fingerprint,
    compiled_stage2b_fingerprint,
    discovery_affordance_catalogue_fingerprint,
    generate_stage2_boundary,
    secondary_secret_catalogue_fingerprint,
    stage2a_affordance_assignment,
    stage2a_valid_example,
    stage2b_valid_example,
    stage2c_valid_example,
    validate_assembled_stage2,
    validate_stage2a_candidate,
    validate_stage2a_discovery_feasibility,
    validate_stage2b_candidate,
    validate_stage2c_candidate,
)
from semantic_pipeline_fixture import semantic_pipeline_payloads


def _fixture() -> dict[str, object]:
    payloads = semantic_pipeline_payloads()
    core = GeneratedCrimeTimelineStage.model_validate(payloads["case_generation_core"])
    case = load_case("ashwick_sample")
    location = load_location("ashwick_manor")
    support = build_stage2_proof_support_catalogue(core)
    discovery = build_discovery_affordance_catalogue(
        core,
        character_ids=case.character_ids,
        location=location,
    )
    secondary = build_secondary_secret_catalogue(core, character_ids=case.character_ids)
    candidate_a = stage2a_valid_example(support)
    stage_a = compile_stage2a_candidate(candidate_a, catalogue=support, core=core)
    candidate_b = stage2b_valid_example(
        stage_2a=stage_a,
        support_catalogue=support,
        discovery_catalogue=discovery,
    )
    stage_b = compile_stage2b_candidate(
        candidate_b,
        stage_2a=stage_a,
        support_catalogue=support,
        discovery_catalogue=discovery,
        core=core,
    )
    candidate_c = stage2c_valid_example(
        stage_2a=stage_a,
        stage_2b=stage_b,
        discovery_catalogue=discovery,
        secondary_catalogue=secondary,
    )
    stage_c = compile_stage2c_candidate(
        candidate_c,
        stage_2a=stage_a,
        stage_2b=stage_b,
        discovery_catalogue=discovery,
        secondary_catalogue=secondary,
        core=core,
    )
    artifact = assemble_stage2_artifact(
        core=core,
        character_ids=case.character_ids,
        location=location,
        support_catalogue=support,
        discovery_catalogue=discovery,
        secondary_catalogue=secondary,
        stage_2a=stage_a,
        stage_2b=stage_b,
        stage_2c=stage_c,
    )
    return locals()


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def test_valid_semantic_pipeline_stops_stage3_ready() -> None:
    f = _fixture()
    artifact = f["artifact"]
    assert artifact.stage_3_readiness.is_valid
    assert len(artifact.compiled_stage_2a.routes) == 2
    assert len(artifact.compiled_stage_2b.evidence) == 6
    assert len(artifact.compiled_stage_2c.red_herrings) == 2
    assert artifact.compiled_stage_2b.fully_non_voluntary_route_ids
    assert artifact.compiled_stage_2b.deferred_stage_3_obligations


@pytest.mark.parametrize("mutation,code", [
    ("unknown", "unknown_support_alias"),
    ("wrong_axis", "wrong_axis_support"),
    ("stale", "stale_proof_support_catalogue"),
])
def test_stage2a_rejects_bad_support_bindings(mutation: str, code: str) -> None:
    f = _fixture()
    candidate = f["candidate_a"]
    document = candidate.model_dump(mode="json")
    if mutation == "stale":
        document["proof_support_catalogue_fingerprint"] = "0" * 64
    elif mutation == "unknown":
        document["routes"][0]["method"]["support_alias"] = "unknown_support"
    else:
        motive_alias = document["routes"][0]["motive"]["support_alias"]
        document["routes"][0]["method"]["support_alias"] = motive_alias
    report = validate_stage2a_candidate(
        Stage2ASemanticCandidate.model_validate(document),
        catalogue=f["support"],
    )
    assert code in _codes(report)


def test_stage2a_rejects_route_logical_gap_even_if_schema_is_bypassed() -> None:
    f = _fixture()
    candidate = f["candidate_a"]
    route = candidate.routes[0].model_copy(update={"reasoning_chain": ("method only",)})
    changed = candidate.model_copy(update={"routes": (route, candidate.routes[1])})
    assert "route_logical_gap" in _codes(
        validate_stage2a_candidate(changed, catalogue=f["support"])
    )


def test_stage2a_rejects_reused_channel_pattern_presented_as_independent() -> None:
    f = _fixture()
    candidate = f["candidate_a"]
    left, right = candidate.routes
    changed_right = right.model_copy(
        update={
            axis: getattr(right, axis).model_copy(
                update={
                    "proposed_channel": getattr(left, axis).proposed_channel,
                    "planned_discovery_mode": getattr(left, axis).planned_discovery_mode,
                    "support_alias": getattr(left, axis).support_alias,
                }
            )
            for axis in ("method", "motive", "opportunity")
        }
    )
    changed = candidate.model_copy(update={"routes": (left, changed_right)})
    codes = _codes(validate_stage2a_candidate(changed, catalogue=f["support"]))
    assert "reused_evidence_channel_pattern" in codes
    assert "shared_planned_proof_channel" in codes


def test_stage2a_proves_an_independent_discovery_allocation_before_stage2b() -> None:
    f = _fixture()
    report = validate_stage2a_discovery_feasibility(
        f["candidate_a"],
        support_catalogue=f["support"],
        discovery_catalogue=f["discovery"],
        core=f["core"],
    )
    assert report.is_valid
    assert stage2a_affordance_assignment(
        f["stage_a"],
        support_catalogue=f["support"],
        discovery_catalogue=f["discovery"],
    ) is not None
    build_stage2b_messages(
        stage_2a=f["stage_a"],
        support_catalogue=f["support"],
        discovery_catalogue=f["discovery"],
    )


def test_stage2a_rejects_channel_and_discovery_mode_mismatch() -> None:
    f = _fixture()
    candidate = f["candidate_a"]
    left, right = candidate.routes
    changed_method = left.method.model_copy(
        update={
            "proposed_channel": EvidenceKind.BEHAVIOURAL,
            "planned_discovery_mode": "physical_search",
        }
    )
    changed = candidate.model_copy(
        update={"routes": (left.model_copy(update={"method": changed_method}), right)}
    )
    assert "channel_discovery_mismatch" in _codes(
        validate_stage2a_candidate(changed, catalogue=f["support"])
    )


def test_stage2a_rejects_two_routes_dependent_on_the_single_body_action() -> None:
    f = _fixture()
    candidate = f["candidate_a"]
    left, right = candidate.routes
    changed_method = right.method.model_copy(
        update={
            "proposed_channel": EvidenceKind.PHYSICAL,
            "planned_discovery_mode": "body_inspection",
        }
    )
    changed = candidate.model_copy(
        update={"routes": (left, right.model_copy(update={"method": changed_method}))}
    )
    report = validate_stage2a_discovery_feasibility(
        changed,
        support_catalogue=f["support"],
        discovery_catalogue=f["discovery"],
        core=f["core"],
    )
    assert "stage_2a_discovery_infeasible" in _codes(report)


def test_stage2b_rejects_shared_critical_discovery_dependency() -> None:
    f = _fixture()
    candidate = f["candidate_b"]
    rows = list(candidate.realizations)
    rows[3] = rows[3].model_copy(
        update={"discovery_affordance_alias": rows[0].discovery_affordance_alias}
    )
    changed = candidate.model_copy(update={"realizations": tuple(rows)})
    assert "shared_critical_discovery_dependency" in _codes(
        validate_stage2b_candidate(
            changed,
            stage_2a=f["stage_a"],
            support_catalogue=f["support"],
            discovery_catalogue=f["discovery"],
            core=f["core"],
        )
    )


def test_stage2b_rejects_same_witness_as_mandatory_bottleneck() -> None:
    f = _fixture()
    stage_a: CompiledStage2A = f["stage_a"]
    roles = dict(stage_a.roles)
    role_values = sorted(roles.values(), key=lambda role: role.role_ref)
    right = next(
        role
        for role in role_values
        if role.proposed_channel == EvidenceKind.TESTIMONIAL
    )
    left = next(
        role
        for role in role_values
        if role.route_id != right.route_id and role.axis == right.axis
    )
    roles[left.role_id] = left.model_copy(
        update={
            "proposed_channel": EvidenceKind.TESTIMONIAL,
            "planned_discovery_mode": "voluntary_testimony",
        }
    )
    changed_a = stage_a.model_copy(update={"roles": roles})
    candidate = f["candidate_b"]
    rows = list(candidate.realizations)
    left_index = next(i for i, item in enumerate(rows) if item.role_ref == left.role_ref)
    right_index = next(i for i, item in enumerate(rows) if item.role_ref == right.role_ref)
    right_row = rows[right_index]
    rows[left_index] = rows[left_index].model_copy(
        update={
            "narrative_form": EvidenceKind.TESTIMONIAL,
            "discovery_affordance_alias": right_row.discovery_affordance_alias,
            "involved_actor_refs": right_row.involved_actor_refs,
            "preservation": "testimonial_memory",
        }
    )
    changed = candidate.model_copy(update={"realizations": tuple(rows)})
    codes = _codes(
        validate_stage2b_candidate(
            changed,
            stage_2a=changed_a,
            support_catalogue=f["support"],
            discovery_catalogue=f["discovery"],
            core=f["core"],
        )
    )
    assert "same_witness_bottleneck" in codes


@pytest.mark.parametrize("mutation,code", [
    ("unknown_affordance", "unsupported_interaction_or_placement"),
    ("impossible_form", "impossible_placement"),
    ("before_event", "evidence_before_source_event"),
    ("rewrite_a", "stage_2b_rewrites_stage_2a"),
])
def test_stage2b_rejects_invalid_realization(mutation: str, code: str) -> None:
    f = _fixture()
    candidate = f["candidate_b"]
    document = candidate.model_dump(mode="json")
    row = document["realizations"][0]
    if mutation == "unknown_affordance":
        row["discovery_affordance_alias"] = "unimplemented_forensic_scan"
    elif mutation == "impossible_form":
        row["narrative_form"] = "testimonial"
    elif mutation == "before_event":
        row["manifestation_delay_minutes"] = -1
    else:
        document["compiled_stage_2a_fingerprint"] = "0" * 64
    changed = Stage2BSemanticCandidate.model_validate(document)
    report = validate_stage2b_candidate(
        changed,
        stage_2a=f["stage_a"],
        support_catalogue=f["support"],
        discovery_catalogue=f["discovery"],
        core=f["core"],
    )
    assert code in _codes(report)


def test_stage2b_rejects_invalid_event_actor_provenance() -> None:
    f = _fixture()
    candidate = f["candidate_b"]
    rows = list(candidate.realizations)
    role = {role.role_ref: role for role in f["stage_a"].roles.values()}[rows[0].role_ref]
    event = next(event for event in f["core"].timeline if event.id == role.canonical_event_id)
    event_actors = set(event.actor_ids) | set(event.observed_by)
    invalid_ref = next(
        ref
        for ref, actor_id in f["discovery"].actor_aliases.items()
        if actor_id not in event_actors
    )
    rows[0] = rows[0].model_copy(update={"involved_actor_refs": (invalid_ref,)})
    changed = candidate.model_copy(update={"realizations": tuple(rows)})
    assert "invalid_event_provenance" in _codes(
        validate_stage2b_candidate(
            changed,
            stage_2a=f["stage_a"],
            support_catalogue=f["support"],
            discovery_catalogue=f["discovery"],
            core=f["core"],
        )
    )


def test_discovery_catalogue_excludes_inaccessible_container() -> None:
    f = _fixture()
    location_data = f["location"].model_dump(mode="json")
    slot_id = next(iter(location_data["evidence_slots"]))
    object_id = location_data["evidence_slots"][slot_id]["object_id"]
    location_data["searchable_objects"][object_id]["requires_item_id"] = "missing_key"
    changed_location = LocationPackage.model_validate(location_data)
    catalogue = build_discovery_affordance_catalogue(
        f["core"],
        character_ids=f["case"].character_ids,
        location=changed_location,
    )
    assert all(item.slot_id != slot_id for item in catalogue.affordances.values())


def test_stage2b_rejects_cyclic_prerequisites() -> None:
    f = _fixture()
    rows = list(f["candidate_b"].realizations)
    rows[0] = rows[0].model_copy(update={"prerequisite_role_refs": (rows[1].role_ref,)})
    rows[1] = rows[1].model_copy(update={"prerequisite_role_refs": (rows[0].role_ref,)})
    candidate = f["candidate_b"].model_copy(update={"realizations": tuple(rows)})
    assert "cyclic_prerequisites" in _codes(
        validate_stage2b_candidate(
            candidate,
            stage_2a=f["stage_a"],
            support_catalogue=f["support"],
            discovery_catalogue=f["discovery"],
            core=f["core"],
        )
    )


def test_stage2b_rejects_missing_route_role() -> None:
    f = _fixture()
    rows = list(f["candidate_b"].realizations)
    rows[-1] = rows[0]
    candidate = f["candidate_b"].model_copy(update={"realizations": tuple(rows)})
    assert "missing_or_duplicate_route_role" in _codes(
        validate_stage2b_candidate(
            candidate,
            stage_2a=f["stage_a"],
            support_catalogue=f["support"],
            discovery_catalogue=f["discovery"],
            core=f["core"],
        )
    )


@pytest.mark.parametrize("mutation,code", [
    ("rewrite_b", "stage_2c_rewrites_true_evidence"),
    ("missing_explanation", "missing_innocent_explanation"),
    ("missing_resolution", "undiscoverable_red_herring_resolution"),
])
def test_stage2c_rejects_invalid_connective_structure(mutation: str, code: str) -> None:
    f = _fixture()
    candidate = f["candidate_c"]
    if mutation == "rewrite_b":
        candidate = candidate.model_copy(update={"compiled_stage_2b_fingerprint": "0" * 64})
    else:
        rows = list(candidate.red_herrings)
        rows[0] = rows[0].model_copy(
            update={
                "innocent_explanation": ""
                if mutation == "missing_explanation"
                else rows[0].innocent_explanation,
                "resolution_affordance_alias": "unknown_resolution"
                if mutation == "missing_resolution"
                else rows[0].resolution_affordance_alias,
            }
        )
        candidate = candidate.model_copy(update={"red_herrings": tuple(rows)})
    report = validate_stage2c_candidate(
        candidate,
        stage_2a=f["stage_a"],
        stage_2b=f["stage_b"],
        discovery_catalogue=f["discovery"],
        secondary_catalogue=f["secondary"],
        core=f["core"],
    )
    assert code in _codes(report)


def test_stage2c_rejects_secondary_event_without_innocent_owner() -> None:
    f = _fixture()
    candidate = f["candidate_c"]
    rows = list(candidate.red_herrings)
    wrong_ref = next(
        ref
        for ref in f["discovery"].actor_aliases
        if ref != rows[0].suspect_ref and ref not in {"victim", "responsible_actor"}
    )
    rows[0] = rows[0].model_copy(update={"involved_actor_refs": (wrong_ref,)})
    changed = candidate.model_copy(update={"red_herrings": tuple(rows)})
    report = validate_stage2c_candidate(
        changed,
        stage_2a=f["stage_a"],
        stage_2b=f["stage_b"],
        discovery_catalogue=f["discovery"],
        secondary_catalogue=f["secondary"],
        core=f["core"],
    )
    assert "secondary_event_missing_owner" in _codes(report)


def test_stage2c_rejects_impossible_secondary_event_window() -> None:
    f = _fixture()
    candidate = f["candidate_c"]
    rows = list(candidate.red_herrings)
    rows[0] = rows[0].model_copy(
        update={
            "secondary_event_earliest_offset_minutes": 120,
            "secondary_event_latest_offset_minutes": -120,
        }
    )
    changed = candidate.model_copy(update={"red_herrings": tuple(rows)})
    report = validate_stage2c_candidate(
        changed,
        stage_2a=f["stage_a"],
        stage_2b=f["stage_b"],
        discovery_catalogue=f["discovery"],
        secondary_catalogue=f["secondary"],
        core=f["core"],
    )
    assert "invalid_secondary_event_window" in _codes(report)


def test_assembled_validator_rejects_true_evidence_exonerating_responsible_actor() -> None:
    f = _fixture()
    solution = f["artifact"].evidence_solution
    evidence = dict(solution.evidence)
    true_id = next(key for key, item in evidence.items() if not item.is_red_herring)
    evidence[true_id] = evidence[true_id].model_copy(
        update={"exonerates_character_ids": (f["stage_a"].responsible_actor_id,)}
    )
    changed = solution.model_copy(update={"evidence": evidence})
    report = validate_assembled_stage2(
        changed,
        core=f["core"],
        character_ids=f["case"].character_ids,
        location=f["location"],
        stage_2a=f["stage_a"],
        stage_2b=f["stage_b"],
        stage_2c=f["stage_c"],
    )
    assert "responsible_actor_exonerated" in _codes(report)


def test_assembled_validator_rejects_red_herring_that_becomes_true_route_evidence() -> None:
    f = _fixture()
    stage_c = f["stage_c"]
    true_fact = next(iter(f["stage_a"].roles.values())).canonical_fact_ids[0]
    red = list(stage_c.red_herrings)
    red[0] = red[0].model_copy(update={"canonical_fact_id": true_fact})
    changed_c = stage_c.model_copy(update={"red_herrings": tuple(red)})
    with pytest.raises(Stage2SemanticError) as raised:
        assemble_stage2_artifact(
            core=f["core"],
            character_ids=f["case"].character_ids,
            location=f["location"],
            support_catalogue=f["support"],
            discovery_catalogue=f["discovery"],
            secondary_catalogue=f["secondary"],
            stage_2a=f["stage_a"],
            stage_2b=f["stage_b"],
            stage_2c=changed_c,
        )
    assert "red_herring_becomes_true_route_evidence" in {
        issue.code for issue in raised.value.issues
    }


def test_assembled_validator_rejects_equally_supported_innocent() -> None:
    f = _fixture()
    solution = f["artifact"].evidence_solution
    evidence = dict(solution.evidence)
    innocent = next(
        actor_id
        for actor_id in f["case"].character_ids
        if actor_id not in {f["core"].murder.murderer_id, f["core"].murder.victim_id}
    )
    for key, item in list(evidence.items()):
        if not item.is_red_herring:
            evidence[key] = item.model_copy(
                update={"implicates_character_ids": (*item.implicates_character_ids, innocent)}
            )
    changed = solution.model_copy(update={"evidence": evidence})
    report = validate_assembled_stage2(
        changed,
        core=f["core"],
        character_ids=f["case"].character_ids,
        location=f["location"],
        stage_2a=f["stage_a"],
        stage_2b=f["stage_b"],
        stage_2c=f["stage_c"],
    )
    assert "responsible_actor_not_uniquely_best_supported" in _codes(report)


def test_patch_rejects_stale_fingerprint_and_unauthorized_path() -> None:
    f = _fixture()
    candidate = f["candidate_a"]
    stale = Stage2SemanticPatch(
        base_fingerprint="0" * 64,
        operations=(Stage2PatchOperation(path="/routes/0/thesis", value="changed"),),
    )
    with pytest.raises(Stage2SemanticError, match="stale") as raised:
        apply_stage2_semantic_patch(
            candidate,
            stale,
            candidate_type=Stage2ASemanticCandidate,
            allowed_paths=("/routes/0/thesis",),
            immutable_paths=("/proof_support_catalogue_fingerprint",),
        )
    assert raised.value.code == "stale_candidate_fingerprint"
    unauthorized = stale.model_copy(
        update={"base_fingerprint": content_fingerprint(candidate.model_dump(mode="json"))}
    )
    with pytest.raises(Stage2SemanticError) as raised:
        apply_stage2_semantic_patch(
            candidate,
            unauthorized,
            candidate_type=Stage2ASemanticCandidate,
            allowed_paths=("/routes/1/thesis",),
            immutable_paths=("/proof_support_catalogue_fingerprint",),
        )
    assert raised.value.code == "unauthorized_patch_path"


def test_genuine_delta_repairs_actual_candidate_and_revalidates() -> None:
    f = _fixture()
    valid = f["candidate_a"]
    document = valid.model_dump(mode="json")
    document["routes"][0]["method"]["support_alias"] = "unknown_support"
    rejected = Stage2ASemanticCandidate.model_validate(document)
    report = validate_stage2a_candidate(rejected, catalogue=f["support"])
    assert "unknown_support_alias" in _codes(report)
    patch = Stage2SemanticPatch(
        base_fingerprint=content_fingerprint(rejected.model_dump(mode="json")),
        operations=(
            Stage2PatchOperation(
                path="/routes/0/method/support_alias",
                value=valid.routes[0].method.support_alias,
            ),
        ),
    )
    repaired = apply_stage2_semantic_patch(
        rejected,
        patch,
        candidate_type=Stage2ASemanticCandidate,
        allowed_paths=("/routes/0/method/support_alias",),
        immutable_paths=("/proof_support_catalogue_fingerprint",),
    )
    assert validate_stage2a_candidate(repaired, catalogue=f["support"]).is_valid


class _FakeLLM:
    def __init__(self, responses: list[SimpleNamespace]):
        self.responses = responses
        self.calls: list[str] = []

    async def generate(self, _messages, *, task_role: str, **_kwargs):
        self.calls.append(task_role)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_accepted_stage2a_checkpoint_resumes_at_stage2b_without_duplicate_call() -> None:
    f = _fixture()
    stage_2a_record: dict[str, object] = {}
    first_llm = _FakeLLM(
        [
            SimpleNamespace(
                content=f["candidate_a"].model_dump_json(),
                finish_reason="stop",
            )
        ]
    )

    def interrupt_after_stage_2a(record: dict[str, object]) -> None:
        stage_2a_record.update(record)
        raise RuntimeError("simulated controller interruption")

    with pytest.raises(RuntimeError, match="simulated controller interruption"):
        await generate_stage2_boundary(
            first_llm,
            repair_llm=first_llm,
            core=f["core"],
            character_ids=f["case"].character_ids,
            location=f["location"],
            accepted_stage_observer=interrupt_after_stage_2a,
        )
    assert first_llm.calls == ["stage2_semantic_2a"]

    resumed_llm = _FakeLLM(
        [
            SimpleNamespace(
                content=f["candidate_b"].model_dump_json(),
                finish_reason="stop",
            ),
            SimpleNamespace(
                content=f["candidate_c"].model_dump_json(),
                finish_reason="stop",
            ),
        ]
    )
    result = await generate_stage2_boundary(
        resumed_llm,
        repair_llm=resumed_llm,
        core=f["core"],
        character_ids=f["case"].character_ids,
        location=f["location"],
        resume_stage_records={"stage2_semantic_2a": stage_2a_record},
    )
    assert result.artifact.stage_3_readiness.is_valid
    assert resumed_llm.calls == ["stage2_semantic_2b", "stage2_semantic_2c"]


@pytest.mark.asyncio
async def test_tampered_stage_checkpoint_fails_before_provider_call() -> None:
    f = _fixture()
    record = {
        "stage": "stage2_semantic_2a",
        "semantic_candidate_fingerprint": "0" * 64,
        "compiled_fingerprint": content_fingerprint(f["stage_a"].model_dump(mode="json")),
        "model_authored_document": f["candidate_a"].model_dump(mode="json"),
        "document": f["stage_a"].model_dump(mode="json"),
    }
    llm = _FakeLLM([])
    with pytest.raises(Stage2SemanticError) as raised:
        await generate_stage2_boundary(
            llm,
            repair_llm=llm,
            core=f["core"],
            character_ids=f["case"].character_ids,
            location=f["location"],
            resume_stage_records={"stage2_semantic_2a": record},
        )
    assert raised.value.code == "checkpoint_invalid"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_truncated_output_is_never_patched() -> None:
    f = _fixture()
    llm = _FakeLLM([SimpleNamespace(content='{"partial":', finish_reason="length")])
    with pytest.raises(Stage2SemanticError) as raised:
        await _generate_semantic_stage(
            llm,
            repair_llm=llm,
            role="stage2_test",
            messages=build_stage2a_messages(f["support"], f["discovery"]),
            candidate_type=Stage2ASemanticCandidate,
            validator=lambda value: validate_stage2a_candidate(value, catalogue=f["support"]),
            compiler=lambda value: compile_stage2a_candidate(value, catalogue=f["support"], core=f["core"]),
            max_tokens=100,
            immutable_paths=("/proof_support_catalogue_fingerprint",),
            max_initial_attempts=1,
            max_delta_repairs=2,
            attempt_observer=None,
            accepted_stage_observer=None,
        )
    assert raised.value.code == "output_truncated"
    assert llm.calls == ["stage2_test"]


@pytest.mark.asyncio
async def test_malformed_output_is_classified_and_not_semantically_patched() -> None:
    f = _fixture()
    llm = _FakeLLM([SimpleNamespace(content="not json", finish_reason="stop")])
    with pytest.raises(Stage2SemanticError) as raised:
        await _generate_semantic_stage(
            llm,
            repair_llm=llm,
            role="stage2_test",
            messages=build_stage2a_messages(f["support"], f["discovery"]),
            candidate_type=Stage2ASemanticCandidate,
            validator=lambda value: validate_stage2a_candidate(value, catalogue=f["support"]),
            compiler=lambda value: compile_stage2a_candidate(value, catalogue=f["support"], core=f["core"]),
            max_tokens=100,
            immutable_paths=("/proof_support_catalogue_fingerprint",),
            max_initial_attempts=1,
            max_delta_repairs=2,
            attempt_observer=None,
            accepted_stage_observer=None,
        )
    assert raised.value.code == "malformed_json"
    assert all("delta_repair" not in call for call in llm.calls)


def test_schema_prevents_host_from_inventing_missing_semantic_meaning() -> None:
    f = _fixture()
    document = f["candidate_b"].model_dump(mode="json")
    document["realizations"][0]["causal_origin"] = ""
    with pytest.raises(ValidationError):
        Stage2BSemanticCandidate.model_validate(document)


def test_prompts_expose_only_current_substage_schema() -> None:
    f = _fixture()
    messages = [
        build_stage2a_messages(f["support"], f["discovery"]),
        build_stage2b_messages(
            stage_2a=f["stage_a"],
            support_catalogue=f["support"],
            discovery_catalogue=f["discovery"],
        ),
        build_stage2c_messages(
            stage_2a=f["stage_a"],
            stage_2b=f["stage_b"],
            discovery_catalogue=f["discovery"],
            secondary_catalogue=f["secondary"],
        ),
    ]
    for pair in messages:
        payload = json.loads(pair[1].content)
        encoded = json.dumps(payload["schema"])
        assert "GeneratedOverlay" not in encoded
        assert "Presentation" not in encoded
        assert "canonical_fact_ids" not in encoded
