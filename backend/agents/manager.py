"""
AgentManager — Phase 3 version.
Creates and manages all NPC agents for a game session.
Routes player→NPC dialogue and starts/stops autonomous agent loops.
"""
from __future__ import annotations
import logging

from agents.base import NPCAgent
from story.models import Scenario, CharacterBriefing
from story.partitioner import get_public_facts
from llm.client import LLMClient
from llm.prompt_builder import build_dialogue_prompt
from world.state import WorldState
from world.event_bus import EventBus
from world.clock import GameClock

logger = logging.getLogger(__name__)


class AgentManager:
    """
    Owns all NPC agents for the active game session.
    Phase 2: handles player→NPC dialogue.
    Phase 3: starts/stops autonomous agent loops, manages game clock.
    """

    def __init__(
        self,
        scenario: Scenario,
        briefings: dict[str, CharacterBriefing],
    ) -> None:
        self.scenario = scenario
        self.public_facts = get_public_facts(scenario)
        self.agents: dict[str, NPCAgent] = {}

        # Create one agent per living NPC in the cast
        for char_def in scenario.cast:
            if char_def.name == scenario.murder.victim:
                continue  # Victim has no agent
            briefing = briefings.get(char_def.name)
            if briefing:
                self.agents[char_def.name] = NPCAgent(
                    char_def=char_def,
                    briefing=briefing,
                    public_facts=self.public_facts,
                )

        logger.info("AgentManager created %d NPC agents.", len(self.agents))

    # ── Autonomous loops ──────────────────────────────────────────────────────

    def start_all_loops(
        self,
        world: WorldState,
        event_bus: EventBus,
        llm: LLMClient,
        clock: GameClock,
    ) -> None:
        """Start autonomous loops for all living agents."""
        for agent in self.agents.values():
            agent.start_loop(world, event_bus, llm, clock)
        logger.info("All %d agent loops started.", len(self.agents))

    def stop_all_loops(self) -> None:
        """Stop all agent loops (called on game end)."""
        for agent in self.agents.values():
            agent.stop_loop()
        logger.info("All agent loops stopped.")

    def get_agent(self, name: str) -> NPCAgent | None:
        return self.agents.get(name)

    # ── Phase 2: Player dialogue ──────────────────────────────────────────────

    async def handle_player_talk(
        self,
        npc_name: str,
        player_name: str,
        player_message: str,
        world: WorldState,
        llm: LLMClient,
    ) -> dict:
        """
        Process a player's message to an NPC.
        Returns {'response': str, 'npc_name': str, 'location': str}
        """
        agent = self.agents.get(npc_name)
        if not agent:
            return {
                "response": "There's nobody here by that name.",
                "npc_name": npc_name,
                "location": "",
            }

        # Location check
        npc_loc_id = world.get_character_location(npc_name)
        player_loc_id = world.get_character_location(player_name)
        npc_loc = world.get_location(npc_loc_id) if npc_loc_id else None
        npc_loc_name = npc_loc.name if npc_loc else "somewhere nearby"

        if npc_loc_id != player_loc_id:
            return {
                "response": f"*{npc_name} isn't in the same room as you.*",
                "npc_name": npc_name,
                "location": npc_loc_id or "",
            }

        # Record the player's message into the agent's memory
        agent.record_player_message(player_name, player_message)

        # Build the dialogue prompt
        messages = build_dialogue_prompt(
            char_def=agent.char_def,
            briefing=agent.briefing,
            memory=agent.memory,
            public_facts=self.public_facts,
            player_name=player_name,
            player_message=player_message,
            player_location=player_loc_id or "",
            current_location_name=npc_loc_name,
        )

        # LLM call
        response_obj = await llm.generate(messages, temperature=0.75, max_tokens=256)
        response_text = response_obj.content.strip()

        # Record the agent's own response
        agent.record_own_response(response_text)

        logger.info("[%s] → [%s]: %s", player_name, npc_name, player_message[:60])
        logger.info("[%s] responded: %s", npc_name, response_text[:80])

        return {
            "response": response_text,
            "npc_name": npc_name,
            "location": npc_loc_id or "",
        }
