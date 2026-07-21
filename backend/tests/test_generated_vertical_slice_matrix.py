"""Provider-free authored-spine projections through the generation boundary.

These tests prove cast independence and end-to-end regression behaviour. They
do not claim that the underlying mystery is procedurally distinct.
"""

from __future__ import annotations

import json
from collections import deque
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from conftest import make_dummy_generated_document
from game.case_generation import select_generation_cast
from game.content import (
    CHARACTER_CARDS_DIR,
    list_content_ids,
    load_case,
    load_character_card,
)


AUTO_SEEDS = (0, 120, 3, 42)


class ProjectedScenarioProvider:
    """One local scenario response; later ID-selection calls may safely fall back."""

    def __init__(self, document: dict[str, object]) -> None:
        self.document = document
        self.scenario_calls = 0
        self.calls = 0
        self.scenario_cast: tuple[str, ...] | None = None

    async def generate(self, messages, **kwargs):
        self.calls += 1
        system = messages[0].content
        if "canonical scenario architect" in system:
            self.scenario_calls += 1
            request = json.loads(messages[1].content)
            self.scenario_cast = tuple(
                request["generation_context"]["selected_character_ids"]
            )
            return SimpleNamespace(content=json.dumps(self.document))
        # Every non-scenario provider boundary is independently fail-closed.
        return SimpleNamespace(content="{}")


def _client(tmp_path) -> TestClient:
    main._session.engine = None
    main._session.llm = None
    main._session.save_root = tmp_path
    return TestClient(main.app)


def _route(doors: list[dict[str, object]], start: str, goal: str) -> list[str]:
    neighbours: dict[str, list[str]] = {}
    for door in doors:
        left, right = str(door["room_a_id"]), str(door["room_b_id"])
        neighbours.setdefault(left, []).append(right)
        if not door["one_way"]:
            neighbours.setdefault(right, []).append(left)
    queue: deque[tuple[str, list[str]]] = deque([(start, [])])
    visited = {start}
    while queue:
        room_id, path = queue.popleft()
        if room_id == goal:
            return path
        for neighbour in neighbours.get(room_id, []):
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append((neighbour, [*path, neighbour]))
    raise AssertionError("public location graph has no route to the body")


def _start_generated(
    client: TestClient,
    seed: int,
    character_ids: tuple[str, ...] | None = None,
) -> tuple[ProjectedScenarioProvider, dict[str, object], str]:
    selected = select_generation_cast(
        seed=seed,
        character_ids=character_ids,
    )
    provider = ProjectedScenarioProvider(
        make_dummy_generated_document(character_ids=selected)
    )
    main._session.llm = provider
    request: dict[str, object] = {
        "seed": seed,
        "location_id": "ashwick_manor",
    }
    if character_ids is not None:
        request["character_ids"] = list(character_ids)
    response = client.post(
        "/api/game/new",
        json=request,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert provider.scenario_calls == 1
    assert provider.scenario_cast == selected
    public_cast = {
        payload["game"]["opening"]["victim_id"]:
        payload["game"]["opening"]["victim_name"],
        **{
            suspect["id"]: suspect["name"]
            for suspect in payload["game"]["suspects"]
        },
    }
    assert set(public_cast) == set(selected)
    assert public_cast == {
        character_id: load_character_card(character_id).data.name
        for character_id in selected
    }
    assert set(main._session.engine.case.character_ids) == set(selected)
    source = load_case("ashwick_sample")
    culprit = dict(zip(source.character_ids, selected, strict=True))[source.murder.murderer_id]
    return provider, payload, culprit


def test_automatic_generation_seed_matrix_covers_all_twenty_four_cards() -> None:
    covered = {
        character_id
        for seed in AUTO_SEEDS
        for character_id in select_generation_cast(seed=seed)
    }
    assert covered == set(list_content_ids(CHARACTER_CARDS_DIR))


def test_normal_generation_accepts_an_arbitrary_exact_manual_cast(tmp_path) -> None:
    pool = tuple(list_content_ids(CHARACTER_CARDS_DIR))
    selected = tuple(pool[::3])
    assert len(selected) == 8

    with _client(tmp_path) as client:
        provider, payload, _culprit_id = _start_generated(
            client,
            seed=9_001,
            character_ids=selected,
        )

    assert payload["generation"]["cast_mode"] == "manual"
    assert provider.scenario_calls == 1


@pytest.mark.parametrize("seed", AUTO_SEEDS)
def test_authored_projection_can_save_reload_after_turn_six_and_win(
    tmp_path,
    seed: int,
) -> None:
    with _client(tmp_path) as client:
        provider, payload, culprit_id = _start_generated(client, seed)
        game = payload["game"]
        location = payload["catalog"]["locations"][0]
        body_room_id = next(
            room["id"]
            for room in location["rooms"]
            if room["name"] == game["opening"]["body_room_name"]
        )
        assert client.post(
            "/api/game/action",
            json={"kind": "advance_opening"},
        ).json()["accepted"]
        game = client.get("/api/game/state").json()
        for destination in _route(location["doors"], game["player_room"]["id"], body_room_id):
            moved = client.post("/api/game/action", json={"kind": "move", "room_id": destination})
            assert moved.status_code == 200 and moved.json()["accepted"]
            game = moved.json()["game"]
        assert client.post(
            "/api/game/action",
            json={"kind": "examine_body"},
        ).json()["accepted"]
        game = client.get("/api/game/state").json()
        desk = next(
            item["id"]
            for item in game["player_room"]["searchable_objects"]
            if "desk" in item["name"].lower()
        )
        fireplace = next(
            item["id"]
            for item in game["player_room"]["searchable_objects"]
            if "fireplace" in item["name"].lower()
        )
        public_events: list[str] = []
        for object_id in (desk, desk, fireplace, fireplace):
            response = client.post(
                "/api/game/action",
                json={"kind": "search", "object_id": object_id},
            )
            assert response.status_code == 200 and response.json()["accepted"]
            turn = response.json()
            game = turn["game"]
            public_events.extend(turn["events"])
        assert game["turn"] >= 6
        assert (
            "A squall strikes the east windows and briefly dims the electric lights."
            in public_events
        )
        facts = {fact["id"]: fact["statement"] for fact in game["known_facts"]}
        assert {"fact_murder_method", "fact_financial_exposure", "fact_murder_time"} <= set(facts)
        evidence_ids = [item["id"] for item in game["discovered_evidence"]]

        save = client.post("/api/game/saves/v1", json={"filename": f"generated-{seed}.json"})
        assert save.status_code == 200
        assert json.loads(
            (tmp_path / f"generated-{seed}.json").read_text(encoding="utf-8")
        )["schema_version"] == 5
        calls_before_reload = provider.calls
        main._session.llm = None
        loaded = client.post(f"/api/game/saves/v1/generated-{seed}.json/load")
        assert loaded.status_code == 200
        assert provider.scenario_calls == 1 and provider.calls == calls_before_reload

        accusation = client.post(
            "/api/game/action",
            json={
                "kind": "accuse",
                "character_id": culprit_id,
                "evidence_ids": evidence_ids,
                "method": facts["fact_murder_method"],
                "motive": facts["fact_financial_exposure"],
                "timeline": facts["fact_murder_time"],
                "timeline_fact_ids": ["fact_murder_time"],
            },
        )
        assert accusation.status_code == 200
        assert accusation.json()["game"]["result"]["solved"] is True
        debrief = client.get("/api/game/debrief")
        assert debrief.status_code == 200
        assert debrief.json()["solution"]["culprit_id"] == culprit_id
        assert provider.calls == calls_before_reload


def test_authored_projection_timeout_is_an_unsolved_debrief(tmp_path) -> None:
    with _client(tmp_path) as client:
        provider, payload, _culprit_id = _start_generated(client, AUTO_SEEDS[0])
        assert client.post(
            "/api/game/action",
            json={"kind": "advance_opening"},
        ).json()["accepted"]
        game = client.get("/api/game/state").json()
        location = payload["catalog"]["locations"][0]
        for _ in range(36):
            if game["phase"] == "ended":
                break
            exits = game["player_room"]["exits"]
            assert exits
            response = client.post("/api/game/action", json={"kind": "move", "room_id": exits[0]})
            assert response.status_code == 200 and response.json()["accepted"]
            game = response.json()["game"]
        assert game["phase"] == "ended"
        assert game["result"]["solved"] is False
        assert game["result"]["end_reason"] == "timeout"
        assert game["result"]["accused_character_id"] is None
        assert "Time expired" in game["result"]["summary"]
        debrief = client.get("/api/game/debrief")
        assert debrief.status_code == 200
        assert debrief.json()["outcome"] == game["result"]
        assert provider.scenario_calls == 1
