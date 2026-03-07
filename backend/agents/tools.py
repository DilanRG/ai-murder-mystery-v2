"""
Agent tool definitions and execution logic.

Tools are the ONLY way NPC agents modify the world state.
Each tool call goes through execute_tool() which:
  1. Validates the call
  2. Mutates world state
  3. Returns a GameEvent to be emitted on the event bus

Tool schema follows OpenRouter / OpenAI function-calling format.
"""
from __future__ import annotations
import logging
import time
import uuid
from typing import Any

from world.state import WorldState, ClueState
from world.event_bus import GameEvent

logger = logging.getLogger(__name__)

# ── Tool Schemas (sent to LLM) ────────────────────────────────────────────────

AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "move_to",
            "description": "Move to an adjacent location. You can only move to rooms directly connected to your current location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_id": {
                        "type": "string",
                        "description": "The ID of the location to move to."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief in-character reason (for internal logging — not shown to player)."
                    }
                },
                "required": ["location_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "speak",
            "description": "Say something aloud. Everyone in your current location will hear this.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "What you say aloud, in character. Keep it 1-3 sentences."
                    }
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "whisper",
            "description": "Whisper privately to one specific person in your current location. Only they will hear it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "The name of the person to whisper to."
                    },
                    "message": {
                        "type": "string",
                        "description": "What you whisper, in character."
                    }
                },
                "required": ["target", "message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "examine",
            "description": "Examine the surroundings carefully. You might notice something others have missed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "What specifically you're looking at or listening for."
                    }
                },
                "required": ["focus"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "plant_evidence",
            "description": "[KILLER ONLY] Secretly plant false evidence to frame another character. Use sparingly — the risk of being seen is real.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "What the planted evidence looks like and what it falsely suggests."
                    },
                    "implicates": {
                        "type": "string",
                        "description": "The character name this evidence is meant to frame."
                    }
                },
                "required": ["description", "implicates"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "destroy_evidence",
            "description": "[KILLER ONLY] Attempt to destroy or conceal a piece of real evidence in your current location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clue_id": {
                        "type": "string",
                        "description": "The ID of the clue to destroy. You can only destroy undiscovered clues."
                    },
                    "method": {
                        "type": "string",
                        "description": "How you destroy it."
                    }
                },
                "required": ["clue_id", "method"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "do_nothing",
            "description": "Stay put, observe, or wait. You take no action this tick.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief internal note about why you're staying put."
                    }
                },
                "required": []
            }
        }
    }
]


# ── Tool Execution ────────────────────────────────────────────────────────────

async def execute_tool(
    agent_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    world: WorldState,
    agent_role: str = "suspect",
) -> GameEvent | None:
    """
    Execute a tool call from an agent. Mutates world state and returns a GameEvent.
    Returns None if the tool call is invalid or has no observable effect.
    """
    loc_id = world.get_character_location(agent_name) or ""
    loc = world.get_location(loc_id)
    loc_name = loc.name if loc else loc_id

    # ── move_to ──────────────────────────────────────────────────────────────
    if tool_name == "move_to":
        target_id = arguments.get("location_id", "")
        adjacent = world.get_adjacent_locations(loc_id)
        if target_id not in adjacent:
            logger.debug("[%s] move_to '%s' blocked — not adjacent.", agent_name, target_id)
            return None
        success = world.move_character(agent_name, target_id)
        if not success:
            return None
        target_loc = world.get_location(target_id)
        return GameEvent(
            event_type="movement",
            actor=agent_name,
            location=target_id,
            description=f"{agent_name} enters {target_loc.name if target_loc else target_id}.",
            data={"from": loc_id, "to": target_id},
            volume="normal",
        )

    # ── speak ─────────────────────────────────────────────────────────────────
    elif tool_name == "speak":
        message = arguments.get("message", "").strip()
        if not message:
            return None
        return GameEvent(
            event_type="speech",
            actor=agent_name,
            location=loc_id,
            description=f'*{loc_name}* {agent_name}: "{message}"',
            data={"raw_message": message},
            volume="normal",
        )

    # ── whisper ───────────────────────────────────────────────────────────────
    elif tool_name == "whisper":
        target = arguments.get("target", "")
        message = arguments.get("message", "").strip()
        if not message or not target:
            return None
        # Verify target is in the same room
        target_loc = world.get_character_location(target)
        if target_loc != loc_id:
            logger.debug("[%s] whisper to '%s' failed — not in same room.", agent_name, target)
            return None
        return GameEvent(
            event_type="speech",
            actor=agent_name,
            location=loc_id,
            description=f"{agent_name} whispers to {target}: \"{message}\"",
            data={"raw_message": message, "to": target},
            volume="whisper",
            target=target,
        )

    # ── examine ───────────────────────────────────────────────────────────────
    elif tool_name == "examine":
        focus = arguments.get("focus", "the room")
        # Agents investigating may discover clues
        clues_here = world.get_clues_at(loc_id)
        discovered_descriptions = []
        for clue in clues_here:
            if clue.difficulty == "easy":
                discovered = world.discover_clue(clue.id, agent_name)
                if discovered:
                    discovered_descriptions.append(discovered.description)
        desc = f"{agent_name} examines {focus} carefully."
        if discovered_descriptions:
            desc += f" Notices: {'; '.join(discovered_descriptions[:2])}"
        return GameEvent(
            event_type="examine",
            actor=agent_name,
            location=loc_id,
            description=desc,
            data={"focus": focus, "found": discovered_descriptions},
            volume="normal",
        )

    # ── plant_evidence (killer only) ──────────────────────────────────────────
    elif tool_name == "plant_evidence":
        if agent_role != "killer":
            logger.warning("[%s] tried plant_evidence but is not killer.", agent_name)
            return None
        description = arguments.get("description", "")
        implicates = arguments.get("implicates", "")
        if not description or not implicates:
            return None
        fake_clue = ClueState(
            id=f"planted_{uuid.uuid4().hex[:8]}",
            description=description,
            location_id=loc_id,
            points_to=implicates,
            difficulty="medium",
            clue_type="physical",
            is_red_herring=True,
        )
        world.add_planted_clue(fake_clue)
        logger.info("[KILLER:%s] planted evidence implicating %s at %s.", agent_name, implicates, loc_name)
        return GameEvent(
            event_type="atmosphere",
            actor=agent_name,
            location=loc_id,
            description=f"Someone has been in {loc_name}. Something feels slightly disturbed.",
            data={"type": "plant", "clue_id": fake_clue.id},
            volume="normal",
        )

    # ── destroy_evidence (killer only) ────────────────────────────────────────
    elif tool_name == "destroy_evidence":
        if agent_role != "killer":
            return None
        clue_id = arguments.get("clue_id", "")
        method = arguments.get("method", "")
        clue = world.clues.get(clue_id)
        if not clue or clue.discovered or clue.location_id != loc_id:
            return None
        # Mark as discovered by killer (effectively removed from findable pool)
        clue.discovered = True
        clue.discovered_by = agent_name
        clue.discovered_at = time.time()
        logger.info("[KILLER:%s] destroyed clue '%s' via %s.", agent_name, clue_id, method)
        return GameEvent(
            event_type="atmosphere",
            actor=agent_name,
            location=loc_id,
            description=f"There's a faint smell of burning paper near the {loc_name}.",
            data={"type": "destroy", "clue_id": clue_id},
            volume="normal",
        )

    # ── do_nothing ────────────────────────────────────────────────────────────
    elif tool_name == "do_nothing":
        return None  # No event emitted

    else:
        logger.warning("[%s] Unknown tool: %s", agent_name, tool_name)
        return None
