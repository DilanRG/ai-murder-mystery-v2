"""Adversarial HTTP checks for the deterministic mystery game.

These deliberately use only the public FastAPI surface.  The point is not to
teach the API about its internals, but to make malformed, repeated, and hostile
client behaviour boring: controlled failures, unchanged state, and no truth
leaks before the game has ended.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import main


FORBIDDEN_TRUTH_KEYS = (
    '"murderer"',
    '"murderer_id"',
    '"private_motive"',
    '"cover_story"',
    '"solution"',
)


def _client(tmp_path: Path) -> TestClient:
    main._session.engine = None
    main._session.llm = None
    main._session.save_root = tmp_path
    return TestClient(main.app)


def _assert_no_truth(payload: object) -> None:
    encoded = json.dumps(payload).lower()
    for forbidden in FORBIDDEN_TRUTH_KEYS:
        assert forbidden not in encoded


def _clock(client: TestClient) -> tuple[int, int, str]:
    response = client.get("/api/game/state")
    assert response.status_code == 200
    game = response.json()
    _assert_no_truth(game)
    return game["turn"], game["in_game_minute"], game["phase"]


def _state(client: TestClient) -> dict[str, object]:
    response = client.get("/api/game/state")
    assert response.status_code == 200
    game = response.json()
    _assert_no_truth(game)
    return game


def _start_investigation(client: TestClient) -> dict[str, object]:
    started = client.post("/api/game/new", json={})
    assert started.status_code == 200
    _assert_no_truth(started.json())
    advanced = client.post("/api/game/action", json={"kind": "advance_opening"})
    assert advanced.status_code == 200 and advanced.json()["accepted"]
    game = advanced.json()["game"]
    _assert_no_truth(game)
    return game


def _assert_rejected_without_time(client: TestClient, payload: object) -> None:
    before = _clock(client)
    response = client.post("/api/game/action", json=payload)
    assert response.status_code != 500, response.text
    assert 400 <= response.status_code < 500 or response.status_code == 200
    if response.status_code == 200:
        body = response.json()
        assert body["accepted"] is False
        _assert_no_truth(body)
    else:
        _assert_no_truth(response.json())
    assert _clock(client) == before


def _move_until_someone_is_present(client: TestClient, game: dict[str, object]) -> dict[str, object]:
    """Use only currently advertised exits to find an interviewable NPC."""

    for _ in range(12):
        if game["present_characters"]:
            return game
        exits = game["player_room"]["exits"]
        assert exits, "The public map must always offer an investigation route."
        moved = client.post("/api/game/action", json={"kind": "move", "room_id": exits[0]})
        assert moved.status_code == 200 and moved.json()["accepted"]
        game = moved.json()["game"]
    raise AssertionError("No public room exposed an interviewable character.")


def test_no_game_and_malformed_payloads_are_boring_and_safe(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        for method, path, payload in (
            ("get", "/api/game/state", None),
            ("get", "/api/game/debrief", None),
            ("post", "/api/game/action", {"kind": "review_notebook"}),
            ("post", "/api/game/saves/v1", {"filename": "slot"}),
        ):
            response = getattr(client, method)(path, json=payload) if payload is not None else getattr(client, method)(path)
            assert response.status_code != 500, response.text
            assert 400 <= response.status_code < 500
            _assert_no_truth(response.json())

        _start_investigation(client)
        for payload in (
            None,
            [],
            "not-an-object",
            {},
            {"kind": "not_real"},
            {"kind": "move", "room_id": "not-a-room", "surprise": True},
            {"kind": "review_notebook", "surprise": True},
            {"kind": "add_note", "text": None},
        ):
            _assert_rejected_without_time(client, payload)


def test_boundary_values_reject_without_clock_mutation_or_truth_leaks(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        game = _start_investigation(client)
        room_id = game["player_room"]["id"]
        catalog = client.get("/api/game/catalog").json()
        non_adjacent_room = next(
            room["id"]
            for room in catalog["locations"][0]["rooms"]
            if room["id"] not in {room_id, *game["player_room"]["exits"]}
        )
        for payload in (
            {"kind": "move", "room_id": room_id},  # one beer: same room
            {"kind": "move", "room_id": non_adjacent_room},
            {"kind": "search", "object_id": "not-an-object"},
            {"kind": "examine_evidence", "evidence_id": "not-discovered"},
            {"kind": "add_note", "text": ""},
            {"kind": "add_note", "text": "n" * 1001},
            {"kind": "add_timeline_entry", "text": "before the estate existed", "minute": -1},
            {"kind": "add_timeline_entry", "text": "in the far future", "minute": 10**9},
            {"kind": "add_timeline_entry", "text": "bad source", "source_ids": ["future_fact"]},
            {"kind": "mark_contradiction", "left_statement_id": "x", "right_statement_id": "x"},
        ):
            _assert_rejected_without_time(client, payload)


def test_interview_and_accusation_extremes_stay_controlled(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        game = _start_investigation(client)
        _assert_rejected_without_time(client, {"kind": "interview_exchange", "message": "hello"})
        _assert_rejected_without_time(client, {"kind": "begin_interview", "character_id": "lady_vivienne_ashford"})

        # A living suspect not currently in the room must not be interviewable.
        present_ids = {character["id"] for character in game["present_characters"]}
        absent = next(suspect["id"] for suspect in game["suspects"] if suspect["id"] not in present_ids)
        _assert_rejected_without_time(client, {"kind": "begin_interview", "character_id": absent})

        game = _move_until_someone_is_present(client, game)
        target = game["present_characters"][0]["id"]
        began = client.post("/api/game/action", json={"kind": "begin_interview", "character_id": target})
        assert began.status_code == 200 and began.json()["accepted"]
        clock = _clock(client)
        for message in ("what did you see?", "one final question", "where were you?"):
            exchange = client.post("/api/game/action", json={"kind": "interview_exchange", "message": message})
            assert exchange.status_code == 200 and exchange.json()["accepted"]
            assert _clock(client) == clock  # an interview is one turn, not three
            _assert_no_truth(exchange.json())

        # The fourth question and a self-contradiction are rejected in-place.
        _assert_rejected_without_time(client, {"kind": "interview_exchange", "message": "one too many"})
        statement_id = client.get("/api/game/state").json()["statements"][0]["id"]
        _assert_rejected_without_time(
            client,
            {"kind": "mark_contradiction", "left_statement_id": statement_id, "right_statement_id": statement_id},
        )
        ended = client.post("/api/game/action", json={"kind": "end_interview"})
        assert ended.status_code == 200 and ended.json()["accepted"]

        victim = "lady_vivienne_ashford"
        _assert_rejected_without_time(client, {"kind": "accuse", "character_id": victim})
        # Blank and mismatched component claims are a valid but unsupported
        # final accusation, never a server error or accidental solve.
        accused = client.post(
            "/api/game/action",
            json={
                "kind": "accuse",
                "character_id": target,
                "method": "",
                "motive": "A completely invented motive",
                "timeline": "A completely invented alibi",
            },
        )
        assert accused.status_code == 200 and accused.json()["accepted"]
        assert accused.json()["game"]["phase"] == "ended"
        assert accused.json()["game"]["result"]["solved"] is False
        repeated = client.post("/api/game/action", json={"kind": "accuse", "character_id": target})
        assert repeated.status_code == 200 and repeated.json()["accepted"] is False


@pytest.mark.parametrize("message", ["", "q" * 10_000])
def test_rejected_interview_text_never_consumes_hidden_session_state(tmp_path: Path, message: str) -> None:
    """Validation failures must precede any canonical statement/session mutation."""

    with _client(tmp_path) as client:
        game = _move_until_someone_is_present(client, _start_investigation(client))
        target = game["present_characters"][0]["id"]
        assert client.post("/api/game/action", json={"kind": "begin_interview", "character_id": target}).json()["accepted"]
        before = _state(client)
        response = client.post("/api/game/action", json={"kind": "interview_exchange", "message": message})
        assert response.status_code != 500, response.text
        assert 400 <= response.status_code < 500
        _assert_no_truth(response.json())
        assert _state(client) == before


def test_many_turns_timeout_and_post_end_rejections(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        game = _start_investigation(client)
        catalog = client.get("/api/game/catalog").json()
        searchable = next(
            obj
            for obj in catalog["locations"][0]["searchable_objects"]
            if obj["room_id"] == game["player_room"]["id"] and not obj["requires_item_id"]
        )
        # Re-searching a spent hotspot still consumes a normal turn, and must
        # remain stable even when it has no more discoveries to offer.
        for _ in range(4):
            searched = client.post("/api/game/action", json={"kind": "search", "object_id": searchable["id"]})
            assert searched.status_code == 200 and searched.json()["accepted"]
            game = searched.json()["game"]
            _assert_no_truth(game)
        # A practical "million beers": far more repetitions than a player
        # needs, all selected from the public state so this remains API-only.
        for _ in range(40):
            if game["phase"] == "ended":
                break
            exits = game["player_room"]["exits"]
            assert exits
            response = client.post("/api/game/action", json={"kind": "move", "room_id": exits[0]})
            assert response.status_code == 200 and response.json()["accepted"]
            game = response.json()["game"]
            _assert_no_truth(game)
        assert game["phase"] == "ended"
        assert game["turn"] == 36
        for payload in (
            {"kind": "review_notebook"},
            {"kind": "move", "room_id": game["player_room"]["id"]},
            {"kind": "accuse", "character_id": "edgar_blackwood"},
        ):
            response = client.post("/api/game/action", json=payload)
            assert response.status_code == 200 and response.json()["accepted"] is False


def test_save_names_and_tampered_documents_are_rejected_safely(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _start_investigation(client)
        baseline = _clock(client)
        for name in ("", "../escape", "..\\escape", "/absolute", "slot" * 40):
            response = client.post("/api/game/saves/v1", json={"filename": name})
            assert response.status_code != 500, response.text
            assert 400 <= response.status_code < 500
            _assert_no_truth(response.json())
            assert _clock(client) == baseline

        good = client.post("/api/game/saves/v1", json={"filename": "good.json"})
        assert good.status_code == 200
        # Directly tamper with files is intentional here: the loader is the
        # hostile trust boundary, not the test client's JSON encoder.
        (tmp_path / "broken.json").write_text("not json", encoding="utf-8")
        (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
        tampered = json.loads((tmp_path / "good.json").read_text(encoding="utf-8"))
        tampered["runtime"]["turn"] = -1
        (tmp_path / "tampered.json").write_text(json.dumps(tampered), encoding="utf-8")
        for filename in ("broken.json", "empty.json", "tampered.json", "../good.json"):
            response = client.post(f"/api/game/saves/v1/{filename}/load")
            assert response.status_code != 500, response.text
            assert 400 <= response.status_code < 500
            _assert_no_truth(response.json())
            assert _clock(client) == baseline

        # A fresh game must discard every old note/timeline/interview trace.
        client.post("/api/game/action", json={"kind": "add_note", "text": "discard me"})
        reset = client.post("/api/game/new", json={})
        assert reset.status_code == 200
        assert reset.json()["game"]["turn"] == 0
        assert reset.json()["game"]["notes"] == []
        _assert_no_truth(reset.json())
