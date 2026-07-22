"""End-to-end acceptance for a non-authored case after autonomous NPC activity."""

from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from procedural_acceptance_fixture import (
    ARBITRARY_CAST,
    independent_generated_document,
)
from conftest import SemanticScenarioFixture


class _AcceptanceProvider:
    """Return one procedural case, then force deterministic agent fallback."""

    def __init__(self) -> None:
        self.calls = 0
        self.document: dict[str, object] | None = None
        self.scenario: SemanticScenarioFixture | None = None

    async def generate(self, messages, **kwargs):
        self.calls += 1
        if self.document is None:
            document = deepcopy(independent_generated_document())
            self.document = document
            self.scenario = SemanticScenarioFixture(document)
        task_role = kwargs.get("task_role", "")
        if task_role == "stage1_semantic_plan" or task_role.startswith("case_generation_"):
            assert self.scenario is not None
            return SimpleNamespace(
                content=json.dumps(self.scenario.response(messages, task_role))
            )
        return SimpleNamespace(content="minus beer")


def _post_action(client: TestClient, **intent):
    response = client.post("/api/game/action", json=intent)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["accepted"], payload
    return payload


def test_generated_case_remains_solvable_after_autonomous_activity_and_replays(
    tmp_path,
) -> None:
    provider = _AcceptanceProvider()
    main._session.engine = None
    main._session.llm = None
    main._session.save_root = tmp_path

    with TestClient(main.app) as client:
        main._session.llm = provider
        started = client.post(
            "/api/game/new",
            json={
                "seed": 731,
                "location_id": "ashwick_manor",
                "character_ids": list(ARBITRARY_CAST),
                "difficulty": "normal",
            },
        )
        assert started.status_code == 200, started.text
        assert main._session.engine is not None
        engine = main._session.engine
        assert engine.case.id.startswith("generated_")
        assert engine.case.id not in {"ashwick_sample", "ashwick_quiet_vow"}
        assert engine.case.character_ids == ARBITRARY_CAST
        assert engine.case.seed == 731

        _post_action(client, kind="advance_opening")

        # Six committed turns exercise deterministic autonomous fallback rather
        # than holding the cast static.  The player repeats a harmless search;
        # NPCs independently move, investigate, socialize, approach, disclose,
        # and react to the turn-six storm event.
        for _ in range(6):
            _post_action(client, kind="search", object_id="hall_clock")

        autonomy_kinds = {
            entry.action_kind for entry in engine.runtime.npc_action_audit
        }
        assert {
            "move",
            "investigate",
            "private_social",
            "approach_player",
            "truthful_disclose",
            "react_world_event",
        } <= autonomy_kinds
        assert {entry.source for entry in engine.runtime.npc_action_audit} == {
            "fallback"
        }

        # One complete proof route remains physically accessible after that
        # activity. Discover it only through normal movement/search actions.
        route = engine.case.solution.evidence_routes[0]
        selected_evidence = [
            *route.method_evidence_ids,
            *route.motive_evidence_ids,
            *route.opportunity_evidence_ids,
        ]
        from test_generated_vertical_slice_matrix import _route

        body_path = _route(
            [door.model_dump(mode="json") for door in engine.location.doors],
            engine.runtime.player_room_id,
            engine.case.opening.body_room_id,
        )
        for room_id in body_path:
            _post_action(client, kind="move", room_id=room_id)
        _post_action(client, kind="examine_body")
        for evidence_id in selected_evidence:
            action = engine.case.evidence[evidence_id].discoverable_via[0]
            object_id = action.split(":", 1)[1]
            room_id = engine.location.searchable_objects[object_id].room_id
            while engine.runtime.player_room_id != room_id:
                # Use a shortest public route when the first exit does not lead
                # directly to the evidence room.
                path = _route(
                    [door.model_dump(mode="json") for door in engine.location.doors],
                    engine.runtime.player_room_id,
                    room_id,
                )
                assert path
                _post_action(client, kind="move", room_id=path[0])
            for _ in range(engine.case.evidence[evidence_id].difficulty.value):
                _post_action(client, kind="search", object_id=object_id)
        assert set(selected_evidence) <= (
            engine.runtime.player_knowledge.discovered_evidence_ids
        )
        method_fact = next(
            engine.case.facts[fact_id]
            for evidence_id in route.method_evidence_ids
            for fact_id in engine.case.evidence[evidence_id].fact_ids
            if engine.case.facts[fact_id].category.value == "means"
        )
        motive_fact = next(
            engine.case.facts[fact_id]
            for evidence_id in route.motive_evidence_ids
            for fact_id in engine.case.evidence[evidence_id].fact_ids
            if engine.case.facts[fact_id].category.value == "motive"
        )
        timeline_fact = engine.case.facts[route.timeline_fact_ids[0]]
        accused = _post_action(
            client,
            kind="accuse",
            character_id=engine.case.murder.murderer_id,
            selected_supporting_evidence_ids=selected_evidence,
            method=method_fact.statement,
            motive=motive_fact.statement,
            timeline=timeline_fact.statement,
            timeline_fact_ids=[timeline_fact.id],
        )
        verdict = accused["game"]["result"]
        assert verdict["correct_culprit"] is True
        assert verdict["method_supported"] is True
        assert verdict["motive_supported"] is True
        assert verdict["timeline_supported"] is True
        assert verdict["evidence_supported"] is True
        assert verdict["contradictions_supported"] is False
        assert verdict["evaluation_score"] == 5
        assert verdict["solved"] is True

        debrief = client.get("/api/game/debrief")
        assert debrief.status_code == 200, debrief.text
        audit = debrief.json()["audit"]
        assert audit["canonical_truth"]["culprit_id"] == engine.case.murder.murderer_id
        assert audit["replay_verification"]["verified"] is True
        assert audit["replay_verification"]["action_count"] == len(
            engine.action_history
        )
        assert audit["replay_verification"]["resolved_npc_action_count"] > 0
        assert len(audit["npc_action_trace"]) == audit["replay_verification"][
            "resolved_npc_action_count"
        ]
        assert {
            entry["kind"] for entry in audit["npc_action_trace"]
        } >= autonomy_kinds

        saved = client.post(
            "/api/game/saves/v2",
            json={"filename": "procedural-acceptance.json"},
        )
        assert saved.status_code == 200, saved.text
        loaded = client.post(
            "/api/game/saves/v2/procedural-acceptance.json/load"
        )
        assert loaded.status_code == 200, loaded.text
        assert loaded.json()["game"] == accused["game"]

    # Six staged calls generated the scenario; subsequent calls were deliberately
    # malformed local planner responses.  No external provider credit is used.
    assert provider.calls > 1
