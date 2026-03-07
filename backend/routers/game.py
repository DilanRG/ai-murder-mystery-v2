"""
routers/game.py — All /api/game/* endpoints.
"""
from __future__ import annotations
import logging
import random
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from world.state import GamePhase
from world.event_bus import GameEvent
from world.clock import GameClock, TimerMode
from story.characters import load_all_characters, select_cast
from story.generator import generate_scenario
from story.partitioner import partition_knowledge
from agents.manager import AgentManager
from world.state import build_world_state
from world.event_bus import EventBus
from llm.client import LLMMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/game")


# ── Request Models ─────────────────────────────────────────────────────────────

class NewGameRequest(BaseModel):
    player_name: str = "Detective"
    player_description: str = ""
    difficulty: str = "normal"   # "easy" | "normal" | "hard"
    timer_mode: str = "none"     # "none" | "realtime" | "event"
    timer_minutes: int = 30


class TalkRequest(BaseModel):
    npc_name: str
    message: str = ""


class MoveRequest(BaseModel):
    location_id: str


class AccuseRequest(BaseModel):
    suspect_name: str
    reasoning: str = ""


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/new")
async def new_game(req: NewGameRequest):
    """
    Start a new game: select cast, generate scenario, initialise world state.
    Long-running async operation — frontend shows loading screen with WS status.
    """
    from routers._deps import get_session, make_llm_client, broadcast

    _session = get_session()
    if not _session.llm:
        raise HTTPException(status_code=400, detail="No LLM configured. Add your API key in Settings.")

    # Cancel any existing agent tasks
    for task in _session.agent_tasks:
        task.cancel()
    _session.agent_tasks.clear()

    async def status(msg: str) -> None:
        await broadcast({"type": "loading_status", "data": {"message": msg}})

    try:
        await status("Selecting the cast...")
        pool = load_all_characters()
        cast = select_cast(pool, count=8)

        await status("Generating the mystery scenario...")
        scenario = await generate_scenario(
            llm=_session.llm,
            cast=cast,
            difficulty=req.difficulty,
            status_callback=status,
        )

        await status("Building the world...")
        start_location = scenario.locations[0].id
        world = build_world_state(scenario, req.player_name, start_location)

        event_bus = EventBus()
        event_bus.set_world(world)
        event_bus.set_ws_sender(broadcast)

        _session.scenario = scenario
        _session.world = world
        _session.event_bus = event_bus
        _session.player_name = req.player_name
        _session.difficulty = req.difficulty
        _session.briefings = partition_knowledge(scenario)
        _session.agent_manager = AgentManager(scenario, _session.briefings)

        world.game_phase = GamePhase.PLAYING

        # Start game clock
        try:
            timer_mode = TimerMode(req.timer_mode)
        except ValueError:
            timer_mode = TimerMode.NONE

        _session.clock = GameClock(
            mode=timer_mode,
            limit_seconds=req.timer_minutes * 60,
            on_time_up=lambda: broadcast({
                "type": "game_phase",
                "data": {"phase": "ended", "reason": "timeout"},
            }),
        )
        _session.clock.start()

        await status("Briefing all suspects...")
        _session.agent_manager.start_all_loops(
            world=world,
            event_bus=event_bus,
            llm=_session.llm,
            clock=_session.clock,
        )

        await broadcast({"type": "game_phase", "data": {"phase": "playing"}})

        return {
            "status": "ok",
            "title": scenario.title,
            "setting": scenario.setting,
            "opening_narration": scenario.opening_narration,
            "victim": scenario.murder.victim,
            "locations": [
                {"id": l.id, "name": l.name, "description": l.description,
                 "connected_to": l.connected_to, "objects": l.objects}
                for l in scenario.locations
            ],
            "cast": [
                {"name": c.name, "description": c.description[:100],
                 "location": world.get_character_location(c.name) or ""}
                for c in cast
            ],
            "player_start": start_location,
        }

    except Exception as e:
        logger.error("New game failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/state")
async def get_game_state():
    """Return the current world state (safe for frontend — no secrets)."""
    from routers._deps import get_session
    _session = get_session()
    if not _session.world:
        raise HTTPException(status_code=400, detail="No active game.")
    return _session.world.to_client_dict(_session.player_name)


@router.post("/move")
async def move_player(req: MoveRequest):
    """Move the player to a location (player ignores adjacency — clicks map freely)."""
    from routers._deps import get_session
    _session = get_session()
    if not _session.world or not _session.is_active():
        raise HTTPException(status_code=400, detail="No active game.")

    old_location = _session.world.get_character_location(_session.player_name) or ""
    success = _session.world.move_player(req.location_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot move to '{req.location_id}'.")

    loc = _session.world.get_location(req.location_id)
    chars_here = _session.world.get_characters_at(req.location_id) - {_session.player_name}

    await _session.event_bus.emit(GameEvent(
        event_type="movement",
        actor=_session.player_name,
        location=req.location_id,
        description=f"{_session.player_name} enters {loc.name if loc else req.location_id}.",
        data={"from": old_location, "to": req.location_id},
    ))

    return {
        "status": "ok",
        "location": {"id": req.location_id, "name": loc.name if loc else req.location_id,
                     "description": loc.description if loc else ""},
        "characters_here": list(chars_here),
        "state": _session.world.to_client_dict(_session.player_name),
    }


@router.post("/talk")
async def talk_to_npc(req: TalkRequest):
    """Player talks to an NPC. Returns LLM dialogue response in character."""
    from routers._deps import get_session
    _session = get_session()
    if not _session.world or not _session.is_active():
        raise HTTPException(status_code=400, detail="No active game.")
    if not _session.agent_manager:
        raise HTTPException(status_code=400, detail="Agent system not initialised.")
    if not _session.llm:
        raise HTTPException(status_code=400, detail="No LLM configured.")
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    result = await _session.agent_manager.handle_player_talk(
        npc_name=req.npc_name,
        player_name=_session.player_name,
        player_message=req.message,
        world=_session.world,
        llm=_session.llm,
    )

    await _session.event_bus.emit(GameEvent(
        event_type="speech",
        actor=result["npc_name"],
        location=result["location"],
        description=result["response"],
        volume="normal",
        data={"to": _session.player_name},
    ))

    return result


@router.post("/investigate")
async def investigate():
    """Investigate the player's current location for clues."""
    from routers._deps import get_session
    _session = get_session()
    if not _session.world or not _session.is_active():
        raise HTTPException(status_code=400, detail="No active game.")

    player_loc = _session.world.get_character_location(_session.player_name)
    available_clues = _session.world.get_clues_at(player_loc)

    DISCOVER_CHANCE = {"easy": 0.9, "medium": 0.5, "hard": 0.2}
    found: list[dict] = []
    for clue in available_clues:
        if random.random() < DISCOVER_CHANCE.get(clue.difficulty, 0.5):
            discovered = _session.world.discover_clue(clue.id, _session.player_name)
            if discovered:
                found.append({
                    "id": discovered.id,
                    "description": discovered.description,
                    "points_to": discovered.points_to,
                    "clue_type": discovered.clue_type,
                    "is_red_herring": discovered.is_red_herring,
                })
                await _session.event_bus.emit(GameEvent(
                    event_type="discovery",
                    actor=_session.player_name,
                    location=player_loc,
                    description=f"Clue found: {discovered.description}",
                    data={"clue_id": discovered.id},
                ))

    return {
        "status": "ok",
        "clues_found": found,
        "location": player_loc,
        "state": _session.world.to_client_dict(_session.player_name),
    }


@router.post("/accuse")
async def accuse(req: AccuseRequest):
    """Make a final accusation — ends the game and generates a narrative ending."""
    from routers._deps import get_session, broadcast
    _session = get_session()
    if not _session.world or not _session.is_active():
        raise HTTPException(status_code=400, detail="No active game.")

    scenario = _session.scenario
    actual_killer = scenario.murder.killer
    correct = req.suspect_name == actual_killer

    _session.world.game_phase = GamePhase.ENDED
    if _session.agent_manager:
        _session.agent_manager.stop_all_loops()
    _session.clock.stop()
    for task in _session.agent_tasks:
        task.cancel()
    _session.agent_tasks.clear()

    # Generate narrative ending (best-effort)
    narrative = ""
    if _session.llm:
        try:
            clues_found = sum(1 for c in _session.world.clues.values() if c.discovered)
            outcome = "solved" if correct else "unsolved"
            prompt = (
                f"Write a short noir-style narrative paragraph (3-4 sentences) describing the outcome.\n"
                f"Title: {scenario.title}\n"
                f"Killer: {scenario.murder.killer} | Victim: {scenario.murder.victim}\n"
                f"Method: {scenario.murder.method} | Motive: {scenario.murder.motive}\n"
                f"The detective ({_session.player_name}) accused: {req.suspect_name}. "
                f"Case {outcome}. Clues found: {clues_found}.\n"
                f"Reasoning: {req.reasoning[:200] or 'None.'}\n"
                f"3-4 sentences only. Cynical narrator voice."
            )
            resp = await _session.llm.generate(
                [LLMMessage(role="user", content=prompt)],
                max_tokens=200, temperature=0.85,
            )
            narrative = resp.content.strip()
        except Exception as e:
            logger.warning("Narrative generation failed: %s", e)

    await broadcast({"type": "game_phase", "data": {
        "phase": "ended", "correct": correct, "narrative": narrative,
    }})

    return {
        "correct": correct,
        "accused": req.suspect_name,
        "actual_killer": actual_killer,
        "method": scenario.murder.method,
        "motive": scenario.murder.motive,
        "verdict": "Case solved." if correct else "The killer walks free.",
        "narrative": narrative,
    }


@router.post("/end")
async def end_game_timeout():
    """Force-end the game when timer expires."""
    from routers._deps import get_session, broadcast
    _session = get_session()
    if not _session.world or _session.world.game_phase != GamePhase.PLAYING:
        return {"status": "not_active"}
    _session.world.game_phase = GamePhase.ENDED
    if _session.agent_manager:
        _session.agent_manager.stop_all_loops()
    _session.clock.stop()
    killer = _session.scenario.murder.killer if _session.scenario else "The killer"
    await broadcast({"type": "game_phase", "data": {
        "phase": "ended", "correct": False, "reason": "timeout",
        "narrative": f"Time ran out. {killer} vanishes into the night.",
    }})
    return {"status": "ended"}


@router.get("/debrief")
async def debrief():
    """Full post-game reveal — all secrets, clues, timeline."""
    from routers._deps import get_session
    _session = get_session()
    if not _session.world or _session.world.game_phase != GamePhase.ENDED:
        raise HTTPException(status_code=400, detail="Game not ended.")

    scenario = _session.scenario
    TIMELINE_TYPES = {"movement", "speech", "discovery", "examine"}
    timeline = [
        {
            "time": round(e.timestamp - _session.world.game_clock_start),
            "type": e.event_type,
            "actor": e.actor,
            "description": e.description,
        }
        for e in _session.world.events
        if e.event_type in TIMELINE_TYPES
    ][:80]

    return {
        "murder": {
            "victim": scenario.murder.victim,
            "killer": scenario.murder.killer,
            "method": scenario.murder.method,
            "motive": scenario.murder.motive,
            "time_of_death": scenario.murder.time_of_death,
            "location": scenario.murder.location_of_death,
            "cover_story": scenario.murder.cover_story,
        },
        "backstory": scenario.backstory,
        "npc_briefings": [
            {
                "name": b.character_name,
                "role": b.role,
                "alibi": b.alibi,
                "true_whereabouts": b.true_whereabouts,
                "secrets": b.secrets,
                "goals": b.goals,
                "suspicions": b.suspicions,
                "emotional_state": b.initial_emotional_state,
            }
            for b in _session.briefings.values()
        ],
        "clues": [
            {
                "id": c.id,
                "description": c.description,
                "points_to": c.points_to,
                "difficulty": c.difficulty,
                "clue_type": c.clue_type,
                "is_red_herring": c.is_red_herring,
                "discovered": c.discovered,
                "planted": c.planted,
            }
            for c in _session.world.clues.values()
        ],
        "red_herrings": [
            {"description": r.description, "implicates": r.implicates, "truth": r.truth}
            for r in scenario.red_herrings
        ],
        "timeline": timeline,
        "stats": {
            "clues_found": sum(1 for c in _session.world.clues.values() if c.discovered and not c.planted),
            "total_clues": sum(1 for c in _session.world.clues.values() if not c.planted),
            "planted_clues_exist": any(c.planted for c in _session.world.clues.values()),
            "elapsed_seconds": round(_session.world.elapsed_seconds),
        },
    }
