"""End-to-end acceptance for a non-authored case after autonomous NPC activity."""

from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from procedural_acceptance_fixture import (
    ARBITRARY_CAST,
    MURDERER_ID,
    independent_generated_document,
)
from conftest import generated_stage_response


class _AcceptanceProvider:
    """Return one procedural case, then force deterministic agent fallback."""

    def __init__(self) -> None:
        self.calls = 0
        self.document: dict[str, object] | None = None

    async def generate(self, messages, **kwargs):
        self.calls += 1
        if self.document is None:
            document = deepcopy(independent_generated_document())
            document["case"]["overlays"][MURDERER_ID]["lies"] = [  # type: ignore[index]
                {
                    "id": "acceptance_return_lie",
                    "topic": "library clock",
                    "claim": "The library clock was running when I left.",
                    "contradicts_fact_ids": ["acceptance_timeline_a"],
                    "disclosed_fact_ids": [],
                    "reason": "The claim conceals the stopped-clock timeline.",
                }
            ]
            self.document = document
        if kwargs.get("task_role", "").startswith("case_generation_"):
            return SimpleNamespace(
                content=json.dumps(
                    generated_stage_response(self.document, kwargs["task_role"])
                )
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

        # The documentary route remains physically accessible after that
        # activity.  Discover it only through normal movement/search actions.
        _post_action(client, kind="move", room_id="library")
        _post_action(client, kind="search", object_id="library_fireplace")
        _post_action(client, kind="search", object_id="library_clock")

        murderer_statement = next(
            statement
            for statement in engine.runtime.player_knowledge.statements
            if statement.speaker_id == MURDERER_ID
            and statement.claim == "I have no involvement in the death."
        )
        witness_statement = next(
            statement
            for statement in engine.runtime.player_knowledge.statements
            if statement.speaker_id == "inspector_maeve_quinn"
            and "acceptance_timeline_a" in statement.referenced_fact_ids
        )
        _post_action(
            client,
            kind="mark_contradiction",
            left_statement_id=murderer_statement.id,
            right_statement_id=witness_statement.id,
            note="The stopped clock contradicts Cross's account.",
        )
        contradiction = engine.runtime.player_knowledge.contradictions[-1]
        assert contradiction.confirmed

        _post_action(client, kind="move", room_id="study")
        _post_action(client, kind="search", object_id="study_desk")

        route = next(
            route
            for route in engine.case.solution.evidence_routes
            if route.id == "route_1"
        )
        selected_evidence = [
            *route.method_evidence_ids,
            *route.motive_evidence_ids,
            *route.opportunity_evidence_ids,
        ]
        assert set(selected_evidence) <= (
            engine.runtime.player_knowledge.discovered_evidence_ids
        )
        facts = {fact.id: fact.statement for fact in engine.case.facts.values()}
        accused = _post_action(
            client,
            kind="accuse",
            character_id=MURDERER_ID,
            selected_supporting_evidence_ids=selected_evidence,
            method=facts["acceptance_means"],
            motive=facts["acceptance_motive"],
            timeline=facts["acceptance_timeline_a"],
            timeline_fact_ids=["acceptance_timeline_a"],
            confirmed_contradiction_ids=[contradiction.id],
        )
        verdict = accused["game"]["result"]
        assert verdict["correct_culprit"] is True
        assert verdict["method_supported"] is True
        assert verdict["motive_supported"] is True
        assert verdict["timeline_supported"] is True
        assert verdict["evidence_supported"] is True
        assert verdict["contradictions_supported"] is True
        assert verdict["evaluation_score"] == 6
        assert verdict["solved"] is True

        debrief = client.get("/api/game/debrief")
        assert debrief.status_code == 200, debrief.text
        audit = debrief.json()["audit"]
        assert audit["canonical_truth"]["culprit_id"] == MURDERER_ID
        assert audit["replay_verification"]["verified"] is True
        assert audit["replay_verification"]["action_count"] == len(
            engine.action_history
        )
        assert audit["replay_verification"]["action_count"] == 14
        assert audit["replay_verification"]["resolved_npc_action_count"] == 84
        assert len(audit["npc_action_trace"]) == 84
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
