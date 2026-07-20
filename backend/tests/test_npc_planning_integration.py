"""Integration tests for previewed, finite NPC intent planning."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from game.actions import AdvanceOpeningIntent, MoveIntent, ReviewNotebookIntent, SearchIntent
from game.content import load_case, load_location
from game.engine import GameEngine
from game.models import EvidenceCondition
from game.service import GameService


class _SelectingLLM:
    def __init__(self, *, malformed: bool = False, prefer_interaction: bool = False) -> None:
        self.calls = 0
        self.malformed = malformed
        self.prefer_interaction = prefer_interaction
        self.saw_interaction = False
        self.selected_summaries: dict[str, str] = {}

    async def generate(self, messages, **kwargs):
        self.calls += 1
        if self.malformed:
            return SimpleNamespace(content="minus beer")
        request = json.loads(messages[-1].content)
        selections = []
        for actor in request["actor_options"]:
            candidates = actor["candidates"]
            interactions = [
                candidate
                for candidate in candidates
                if "local interaction" in candidate["summary"]
            ]
            moves = [
                candidate
                for candidate in candidates
                if candidate["summary"].startswith("Move by")
            ]
            if interactions:
                self.saw_interaction = True
            chosen = (
                interactions[0]
                if self.prefer_interaction and interactions
                else moves[-1] if moves else candidates[0]
            )
            self.selected_summaries[actor["actor_id"]] = chosen["summary"]
            selections.append(
                {"actor_id": actor["actor_id"], "action_id": chosen["action_id"]}
            )
        return SimpleNamespace(content=json.dumps({"selections": selections}))


def _service(tmp_path: Path, llm=None) -> GameService:
    service = GameService(tmp_path, llm=llm)
    service.start()
    return service


def test_exactly_one_batch_call_for_committed_action_and_zero_for_free_or_rejected(
    tmp_path: Path,
) -> None:
    llm = _SelectingLLM()
    service = _service(tmp_path, llm)

    opening = asyncio.run(service.action(AdvanceOpeningIntent()))
    free = asyncio.run(service.action(ReviewNotebookIntent()))
    rejected = asyncio.run(service.action(MoveIntent(room_id="not_a_room")))
    assert opening["accepted"] and not opening["committed"]
    assert free["accepted"] and not free["committed"]
    assert not rejected["accepted"]
    assert llm.calls == 0

    destination = service.state().player_room.exits[0]
    committed = asyncio.run(service.action(MoveIntent(room_id=destination)))
    assert committed["accepted"] and committed["committed"]
    assert llm.calls == 1


def test_valid_provider_movement_is_mapped_to_an_engine_candidate(tmp_path: Path) -> None:
    llm = _SelectingLLM()
    service = _service(tmp_path, llm)
    asyncio.run(service.action(AdvanceOpeningIntent()))

    before = {
        actor_id: state.current_room_id
        for actor_id, state in service.engine.runtime.characters.items()
    }
    destination = service.state().player_room.exits[0]
    asyncio.run(service.action(MoveIntent(room_id=destination)))

    moved_actors = []
    for actor_id, summary in llm.selected_summaries.items():
        if summary.startswith("Move by"):
            expected_name = summary.removeprefix("Move by an available route to ").removesuffix(".")
            room_id = service.engine.runtime.characters[actor_id].current_room_id
            assert service.engine.location.rooms[room_id].name == expected_name
            if room_id != before[actor_id]:
                moved_actors.append(actor_id)
    assert moved_actors


def test_malformed_provider_has_exact_deterministic_fallback_parity(tmp_path: Path) -> None:
    direct = GameEngine(load_case("ashwick_sample"), load_location("ashwick_manor"))
    direct.apply(AdvanceOpeningIntent())
    service = _service(tmp_path, _SelectingLLM(malformed=True))
    asyncio.run(service.action(AdvanceOpeningIntent()))

    destination = direct.view().player_room.exits[0]
    direct_result = direct.apply(MoveIntent(room_id=destination))
    service_result = asyncio.run(service.action(MoveIntent(room_id=destination)))

    assert direct_result.accepted and service_result["accepted"]
    assert service.llm.calls == 1
    assert service.engine.runtime == direct.runtime


def test_same_turn_discovery_cannot_be_selected_for_manipulation(tmp_path: Path) -> None:
    llm = _SelectingLLM(prefer_interaction=True)
    service = _service(tmp_path, llm)
    service.engine.apply(AdvanceOpeningIntent())
    runtime = service.engine.runtime
    runtime.turn = 2
    runtime.player_room_id = "library"
    runtime.characters["edgar_blackwood"].current_room_id = "library"
    runtime.searchable_objects["library_desk"].search_count = 1

    result = asyncio.run(service.action(SearchIntent(object_id="library_desk")))

    assert result["accepted"] and result["committed"]
    assert "ev_edgar_cuff_fibre" in runtime.player_knowledge.discovered_evidence_ids
    assert runtime.evidence["ev_edgar_cuff_fibre"].condition is EvidenceCondition.COLLECTED
    assert not llm.saw_interaction


def test_preview_never_mutates_original_engine_even_for_committed_action() -> None:
    engine = GameEngine(load_case("ashwick_sample"), load_location("ashwick_manor"))
    engine.apply(AdvanceOpeningIntent())
    before = engine.runtime.model_copy(deep=True)
    destination = engine.view().player_room.exits[0]

    committed = engine.preview(MoveIntent(room_id=destination))
    rejected = engine.preview(MoveIntent(room_id="not_a_room"))

    assert committed.result.accepted and committed.result.committed
    assert committed.npc_request is not None
    assert not rejected.result.accepted and rejected.npc_request is None
    assert engine.runtime == before
