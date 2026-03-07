"""
NPCAgent — Phase 3 extended version.
Phase 2: responds to player dialogue.
Phase 3: autonomous perceive → think → tool_call → sleep loop.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import TYPE_CHECKING

from story.models import CharacterDef, CharacterBriefing
from agents.memory import AgentMemory
from agents.perception import get_perception
from agents.tools import AGENT_TOOLS, execute_tool

if TYPE_CHECKING:
    from llm.client import LLMClient, LLMMessage
    from world.state import WorldState
    from world.event_bus import EventBus
    from world.clock import GameClock

logger = logging.getLogger(__name__)


# ── Autonomous agent system prompt ────────────────────────────────────────────

def _build_autonomous_system_prompt(
    char_def: CharacterDef,
    briefing: CharacterBriefing,
    public_facts: str,
) -> str:
    """System prompt for the agent's autonomous action loop (not the player dialogue)."""
    role_addendum = ""
    if briefing.role == "killer":
        role_addendum = f"""
CRITICAL CONTEXT — YOU ARE THE KILLER:
{briefing.murder_knowledge or "You know what you did."}
You are terrified of discovery. Your frame target is {briefing.frame_target or "no one in particular"}.
You must act to protect yourself: destroy evidence, plant suspicion, maintain your cover story.
But do not act so obviously that you arouse suspicion. You are still a person with a life to protect.
"""

    return f"""You are {char_def.name}, a character in a live murder mystery.

{public_facts}

YOUR CHARACTER:
{char_def.description}
Personality: {char_def.personality}
Voice/manner: {char_def.voice}
Background: {char_def.background}
Your emotional state: {briefing.initial_emotional_state}
Your alibi: {briefing.alibi}
Your true whereabouts: {briefing.true_whereabouts}
Your secrets: {'; '.join(briefing.secrets)}
What you genuinely know: {'; '.join(briefing.knowledge)}
Your suspicions: {briefing.suspicions}
Your goals during this investigation: {'; '.join(briefing.goals)}
{role_addendum}

BEHAVIOUR RULES:
- You live your life authentically. You are not a passive prop.
- Move between rooms with purpose. Visit places that make sense for your character.
- Talk to other characters when you encounter them — naturally, not robotically.
- Do NOT confess or let slip the truth easily. Protect your secrets.
- If alone with no clear agenda, use do_nothing — don't force action.
- Keep spoken messages SHORT: 1–2 sentences max. This is live conversation.
- Use your perception to decide your next action. React to what you see and hear.
"""


class NPCAgent:
    """
    An NPC agent with full autonomous lifecycle.

    Phase 2: responds to player dialogue (handle_player_dialogue).
    Phase 3: runs perceive → think → act loop via run_loop().
    """

    def __init__(
        self,
        char_def: CharacterDef,
        briefing: CharacterBriefing,
        public_facts: str = "",
    ) -> None:
        self.char_def = char_def
        self.briefing = briefing
        self.public_facts = public_facts
        self.memory = AgentMemory(character_name=char_def.name)
        self.name = char_def.name
        self.role = briefing.role

        # Autonomous loop state
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._consecutive_idle = 0

    # ── Phase 2: Player dialogue ──────────────────────────────────────────────

    def record_player_message(self, player_name: str, message: str) -> None:
        self.memory.add_conversation(player_name, message, time.time())
        if not self.memory.questioned_by_player:
            self.memory.questioned_by_player = True

    def record_own_response(self, response: str) -> None:
        self.memory.add_conversation(self.name, response, time.time())

    def record_witnessed_event(self, description: str) -> None:
        self.memory.add_witnessed_event(description)

    # ── Phase 3: Autonomous loop ──────────────────────────────────────────────

    def start_loop(
        self,
        world: "WorldState",
        event_bus: "EventBus",
        llm: "LLMClient",
        clock: "GameClock",
    ) -> None:
        """Spin up the agent's autonomous action loop as a background Task."""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(
            self._agent_loop(world, event_bus, llm, clock),
            name=f"agent_loop_{self.name}",
        )
        logger.info("[%s] autonomous loop started.", self.name)

    def stop_loop(self) -> None:
        """Cancel the agent's autonomous loop."""
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            logger.info("[%s] autonomous loop stopped.", self.name)

    async def _agent_loop(
        self,
        world: "WorldState",
        event_bus: "EventBus",
        llm: "LLMClient",
        clock: "GameClock",
    ) -> None:
        """Core perceive → think → act loop. Runs until _running is False."""
        from llm.client import LLMMessage  # local import to avoid circular

        # Stagger startup so all agents don't fire at the same time
        import random
        await asyncio.sleep(random.uniform(2, 8))

        while self._running:
            try:
                await self._tick(world, event_bus, llm, clock)
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log and continue — one bad tick shouldn't kill the loop
                logger.error("[%s] loop tick error: %s", self.name, e, exc_info=True)
                await asyncio.sleep(10)

    async def _tick(
        self,
        world: "WorldState",
        event_bus: "EventBus",
        llm: "LLMClient",
        clock: "GameClock",
    ) -> None:
        """One perceive → think → act cycle."""
        from llm.client import LLMMessage  # local import

        # 1. Perceive current state
        perception = get_perception(self.name, world)
        chars_in_room = len(perception.characters_present)

        # 2. Build prompt
        system = _build_autonomous_system_prompt(
            self.char_def, self.briefing, self.public_facts
        )
        perception_block = perception.format_for_prompt()

        # Inject recent witnessed events into context
        witnessed_block = ""
        recent = self.memory.witnessed_events[-5:] if self.memory.witnessed_events else []
        if recent:
            witnessed_block = "RECENT EVENTS YOU WITNESSED:\n" + "\n".join(f"- {e}" for e in recent)

        user_content = f"""CURRENT SITUATION:
{perception_block}

{witnessed_block}

INSTRUCTIONS:
Based on your perception and character, choose ONE action from the available tools.
Think briefly: what would your character naturally do right now?
"""

        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user_content),
        ]

        # 3. LLM call (tool-calling mode)
        try:
            response = await llm.generate_with_tools(
                messages,
                tools=AGENT_TOOLS,
                max_tokens=256,
            )
        except Exception as e:
            logger.warning("[%s] LLM call failed: %s", self.name, e)
            await asyncio.sleep(clock.get_agent_tick(chars_in_room))
            return

        # 4. Execute tool calls
        if response.tool_calls:
            for tool_call in response.tool_calls:
                event = await execute_tool(
                    agent_name=self.name,
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    world=world,
                    agent_role=self.role,
                )
                if event:
                    await event_bus.emit(event)
                    # Record the action in self-memory
                    self.memory.add_witnessed_event(f"I {tool_call.name}: {event.description}")
                    self._consecutive_idle = 0
                    logger.debug("[%s] executed %s → %s", self.name, tool_call.name, event.description[:60])

        elif response.content:
            # Model returned text instead of a tool call — treat as speech if substantive
            text = response.content.strip()
            if len(text) > 10 and chars_in_room > 0:
                from world.event_bus import GameEvent
                loc_id = world.get_character_location(self.name) or ""
                event = await execute_tool(
                    agent_name=self.name,
                    tool_name="speak",
                    arguments={"message": text[:200]},
                    world=world,
                    agent_role=self.role,
                )
                if event:
                    await event_bus.emit(event)
        else:
            self._consecutive_idle += 1

        # 5. Sleep (adaptive tick rate)
        tick = clock.get_agent_tick(chars_in_room)
        # Increase sleep if agent has been idle repeatedly
        if self._consecutive_idle >= 3:
            tick = GameClock.TICK_IDLE
        await asyncio.sleep(tick)
