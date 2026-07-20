"""A player-visible, API-only regression playthrough.

This test intentionally knows no authored case model or engine internals.  Its
only map, clue, notebook, and accusation inputs are values received from the
HTTP API, mirroring a real local client.
"""

from __future__ import annotations

import json
from collections import deque

from fastapi.testclient import TestClient

import main


def _client(tmp_path):
    main._session.engine = None
    main._session.llm = None
    main._session.save_root = tmp_path
    return TestClient(main.app)


def _route(doors: list[dict[str, object]], start: str, goal: str) -> list[str]:
    """Find a public-door route, leaving traversal validation to current exits."""

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
    raise AssertionError("the public map has no route to the body room")


def _assert_no_solution_leak(payload: object) -> None:
    serialized = json.dumps(payload).lower()
    for forbidden in ('"murderer"', "private_motive", "cover_story", '"solution"'):
        assert forbidden not in serialized


def test_public_api_vertical_slice_playthrough_and_restore(tmp_path) -> None:
    with _client(tmp_path) as client:
        new_game = client.post("/api/game/new", json={})
        assert new_game.status_code == 200
        new_payload = new_game.json()
        opening_game = new_payload["game"]
        catalog = new_payload["catalog"]
        _assert_no_solution_leak(new_payload)

        # The opening tells the client the body-room name; the public catalog
        # translates that name to an ID and supplies its public door graph.
        location = catalog["locations"][0]
        body_room_id = next(
            room["id"]
            for room in location["rooms"]
            if room["name"] == opening_game["opening"]["body_room_name"]
        )
        assert client.get("/api/game/debrief").status_code == 400

        advanced = client.post("/api/game/action", json={"kind": "advance_opening"})
        assert advanced.status_code == 200
        game = advanced.json()["game"]
        assert game["phase"] == "investigation"
        _assert_no_solution_leak(game)

        for destination in _route(location["doors"], game["player_room"]["id"], body_room_id):
            # The UI may only offer destinations that are currently unlocked.
            assert destination in game["player_room"]["exits"]
            moved = client.post("/api/game/action", json={"kind": "move", "room_id": destination})
            assert moved.status_code == 200 and moved.json()["accepted"]
            game = moved.json()["game"]
        assert game["player_room"]["id"] == body_room_id

        body = client.post("/api/game/action", json={"kind": "examine_body"})
        assert body.status_code == 200 and body.json()["committed"]
        game = body.json()["game"]
        assert game["discovered_evidence"]

        # Select an actual player-visible hotspot rather than relying on a
        # canonical object ID.  A careful second pass is part of the game loop.
        desk = next(
            hotspot["id"]
            for hotspot in game["player_room"]["searchable_objects"]
            if "desk" in hotspot["name"].lower()
        )
        for _ in range(2):
            searched = client.post("/api/game/action", json={"kind": "search", "object_id": desk})
            assert searched.status_code == 200 and searched.json()["accepted"]
            game = searched.json()["game"]
        evidence_ids = [evidence["id"] for evidence in game["discovered_evidence"]]
        facts = {fact["id"]: fact["statement"] for fact in game["known_facts"]}
        assert len(evidence_ids) >= 3
        assert {"fact_murder_method", "fact_financial_exposure", "fact_murder_time"} <= set(facts)
        _assert_no_solution_leak(game)

        note = client.post("/api/game/action", json={"kind": "add_note", "text": "Compare the physical and financial clues."})
        assert note.status_code == 200 and note.json()["accepted"]
        timeline = client.post(
            "/api/game/action",
            json={
                "kind": "add_timeline_entry",
                "text": facts["fact_murder_time"],
                "source_ids": [evidence_ids[0]],
            },
        )
        assert timeline.status_code == 200 and timeline.json()["accepted"]
        saved_state = timeline.json()["game"]
        assert saved_state["notes"] and saved_state["timeline"]

        saved = client.post("/api/game/saves/v1", json={"filename": "public-playthrough.json"})
        assert saved.status_code == 200
        # Mutate runtime only through a player-visible action, then prove that
        # reload restores the mid-investigation snapshot.
        mutation = client.post("/api/game/action", json={"kind": "search", "object_id": desk})
        assert mutation.status_code == 200 and mutation.json()["game"]["turn"] > saved_state["turn"]
        loaded = client.post("/api/game/saves/v1/public-playthrough.json/load")
        assert loaded.status_code == 200
        restored = loaded.json()["game"]
        for field in ("turn", "in_game_minute", "discovered_evidence", "known_facts", "notes", "timeline"):
            assert restored[field] == saved_state[field]

        # Claims come from public known facts.  The target is deterministic
        # fixture knowledge, while all supporting IDs and text are client data.
        suspect_ids = {suspect["id"] for suspect in restored["suspects"]}
        assert "edgar_blackwood" in suspect_ids
        accusation = client.post(
            "/api/game/action",
            json={
                "kind": "accuse",
                "character_id": "edgar_blackwood",
                "evidence_ids": evidence_ids,
                "method": facts["fact_murder_method"],
                "motive": facts["fact_financial_exposure"],
                "timeline": facts["fact_murder_time"],
                "timeline_fact_ids": ["fact_murder_time"],
            },
        )
        assert accusation.status_code == 200
        result = accusation.json()["game"]
        assert result["phase"] == "ended"
        assert result["result"]["solved"] is True
        assert result["result"]["support_score"] >= 2

        debrief = client.get("/api/game/debrief")
        assert debrief.status_code == 200
        assert debrief.json()["solution"]["culprit_id"] == "edgar_blackwood"
