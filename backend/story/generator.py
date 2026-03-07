"""
Story generator — takes the selected cast and produces a complete murder mystery scenario
via a single structured LLM call. This is the most critical prompt in the game.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Any

from llm.client import LLMClient, LLMMessage
from story.models import (
    Scenario, CharacterDef, LocationDef, ClueDef, RedHerring,
    MurderDetails, CharacterBriefing,
)
from config.settings import MIN_LOCATIONS, MAX_LOCATIONS, MIN_CLUES, MAX_CLUES

logger = logging.getLogger(__name__)

# ── System Prompt ────────────────────────────────────────────────────────────

STORY_SYSTEM_PROMPT = """\
You are the creative director of a murder mystery game. You will be given a cast of characters \
and must generate a complete, original murder mystery scenario.

Your output must be a single valid JSON object, exactly matching the schema below. \
Do not include any text before or after the JSON.

REQUIREMENTS:
- The mystery must be internally consistent — every clue, alibi, and timeline detail must fit together.
- Characters should be morally grey — no pure heroes or pure villains. Everyone has something to hide.
- The killer's motive must feel earned and human, not cartoonishly evil.
- Include exactly {num_locations} distinct locations, {num_clues} clues, and {num_red_herrings} red herrings.
- Clues: roughly 40% easy, 40% medium, 20% hard. Each clue must be findable via dialogue or investigation.
- Red herrings must be plausible but ultimately explainable.
- Each character briefing must reflect only what THAT character genuinely knows.
- The killer's briefing must convey the full weight and psychological burden of their act — \
  the gravity of having taken a life, the paranoia of discovery, the desperation to escape justice. \
  Make the killer feel like a person who made a terrible choice under pressure, not a sociopath.

DIFFICULTY: {difficulty}
- easy: more easy clues (60%), NPCs hint freely, killer less careful
- normal: balanced (40/40/20), NPCs moderately guarded
- hard: fewer easy clues (20%), NPCs evasive, killer well-prepared

SCHEMA:
{{
  "title": "string — evocative mystery title",
  "setting": "string — one line: location type, era, atmosphere",
  "atmosphere": "string — 2-3 sentences of mood and tone",
  "opening_narration": "string — 3-4 sentences. Cinematic intro read to the player. Sets the scene after the murder is discovered.",
  "backstory": "string — 2-3 paragraphs. History of relationships and tensions leading to the murder.",
  "murder": {{
    "victim": "character name",
    "killer": "character name",
    "method": "string — specific, vivid description of how",
    "motive": "string — the underlying human reason",
    "time_of_death": "string — narrative time",
    "location_of_death": "location id",
    "cover_story": "string — what the killer wants everyone to believe happened"
  }},
  "locations": [
    {{
      "id": "snake_case_id",
      "name": "Display Name",
      "description": "string — atmospheric single paragraph",
      "connected_to": ["other_location_id"],
      "objects": ["list of examinable objects here"]
    }}
  ],
  "clues": [
    {{
      "id": "clue_01",
      "description": "string — what the player finds/hears",
      "location": "location_id",
      "points_to": "character name this implicates",
      "difficulty": "easy|medium|hard",
      "clue_type": "physical|testimony|document|behavioral",
      "is_red_herring": false
    }}
  ],
  "red_herrings": [
    {{
      "description": "string — the misleading lead",
      "implicates": "character name",
      "truth": "string — the real innocent explanation"
    }}
  ],
  "character_briefings": {{
    "Character Name": {{
      "role": "killer|suspect|witness",
      "alibi": "string — what they claim their whereabouts were",
      "true_whereabouts": "string — what actually happened (may differ from alibi)",
      "knowledge": ["list of things they genuinely know about events that night"],
      "secrets": ["personal secrets unrelated or tangentially related to the murder"],
      "goals": ["what they want to achieve during the investigation"],
      "relationships": {{"Other Character": "how they feel about them"}},
      "initial_emotional_state": "string",
      "suspicions": "string — who they suspect and why, narrative form",
      "murder_knowledge": null,
      "frame_target": null
    }}
  }}
}}

For the KILLER's briefing ONLY, set:
- "murder_knowledge": a full first-person account of what they did and why — written with psychological depth, despair, and the weight of their action
- "frame_target": the character name they intend to blame (or null if they're relying on confusion)
"""

USER_PROMPT_TEMPLATE = """\
Generate a murder mystery scenario using the following cast:

{cast_descriptions}

Generate {num_locations} locations, {num_clues} clues, and {num_red_herrings} red herrings.
Difficulty: {difficulty}

Remember: JSON only, no extra text.\
"""


def _build_cast_description(cast: list[CharacterDef]) -> str:
    lines = []
    for c in cast:
        lines.append(
            f"- {c.name} ({c.moral_alignment}): {c.description[:200]}\n"
            f"  Personality: {c.personality}\n"
            f"  Possible roles: {', '.join(c.possible_roles)}\n"
            f"  Secrets they carry: {'; '.join(c.secrets[:2])}"
        )
    return "\n\n".join(lines)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Multi-strategy JSON extraction — handles markdown fences + leading/trailing noise."""
    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strategy 2: strip markdown fences
    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped.strip())
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Strategy 3: find first { ... } spanning the whole document
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _parse_scenario(data: dict[str, Any], cast: list[CharacterDef]) -> Scenario:
    """Convert raw JSON dict into a typed Scenario object."""
    murder = MurderDetails(
        victim=data["murder"]["victim"],
        killer=data["murder"]["killer"],
        method=data["murder"]["method"],
        motive=data["murder"]["motive"],
        time_of_death=data["murder"]["time_of_death"],
        location_of_death=data["murder"]["location_of_death"],
        cover_story=data["murder"]["cover_story"],
    )
    locations = [
        LocationDef(
            id=loc["id"],
            name=loc["name"],
            description=loc["description"],
            connected_to=loc.get("connected_to", []),
            objects=loc.get("objects", []),
        )
        for loc in data["locations"]
    ]
    clues = [
        ClueDef(
            id=c["id"],
            description=c["description"],
            location=c["location"],
            points_to=c["points_to"],
            difficulty=c["difficulty"],
            clue_type=c["clue_type"],
            is_red_herring=c.get("is_red_herring", False),
        )
        for c in data["clues"]
    ]
    red_herrings = [
        RedHerring(
            description=r["description"],
            implicates=r["implicates"],
            truth=r["truth"],
        )
        for r in data["red_herrings"]
    ]
    briefings: dict[str, CharacterBriefing] = {}
    for char_name, b in data["character_briefings"].items():
        briefings[char_name] = CharacterBriefing(
            character_name=char_name,
            role=b["role"],
            alibi=b["alibi"],
            true_whereabouts=b["true_whereabouts"],
            knowledge=b.get("knowledge", []),
            secrets=b.get("secrets", []),
            goals=b.get("goals", []),
            relationships=b.get("relationships", {}),
            initial_emotional_state=b.get("initial_emotional_state", "tense"),
            suspicions=b.get("suspicions", ""),
            murder_knowledge=b.get("murder_knowledge"),
            frame_target=b.get("frame_target"),
        )
    return Scenario(
        title=data["title"],
        setting=data["setting"],
        atmosphere=data["atmosphere"],
        opening_narration=data["opening_narration"],
        backstory=data["backstory"],
        murder=murder,
        locations=locations,
        clues=clues,
        red_herrings=red_herrings,
        character_briefings=briefings,
        cast=cast,
    )


async def generate_scenario(
    llm: LLMClient,
    cast: list[CharacterDef],
    difficulty: str = "normal",
    status_callback=None,
) -> Scenario:
    """
    Generate a complete murder mystery scenario from the cast.
    Makes a single LLM call with a large structured prompt and parses the JSON output.
    Falls back and retries once on parse failure.
    """
    num_locations = 6
    num_clues = 8
    num_red_herrings = 3

    if difficulty == "easy":
        num_clues = 10
        num_red_herrings = 2
    elif difficulty == "hard":
        num_clues = 6
        num_red_herrings = 4

    system = STORY_SYSTEM_PROMPT.format(
        num_locations=num_locations,
        num_clues=num_clues,
        num_red_herrings=num_red_herrings,
        difficulty=difficulty,
    )
    user_msg = USER_PROMPT_TEMPLATE.format(
        cast_descriptions=_build_cast_description(cast),
        num_locations=num_locations,
        num_clues=num_clues,
        num_red_herrings=num_red_herrings,
        difficulty=difficulty,
    )

    messages = [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user_msg),
    ]

    if status_callback:
        await status_callback("Consulting the AI director for the scenario...")

    for attempt in range(2):
        try:
            response = await llm.generate(
                messages,
                max_tokens=4096,
                temperature=0.85,
                json_mode=False,  # Some models don't support json_mode
            )
            raw = response.content
            data = _extract_json(raw)
            if data is None:
                raise ValueError("Could not extract JSON from LLM output.")

            if status_callback:
                await status_callback("Weaving the backstory and hiding the evidence...")

            scenario = _parse_scenario(data, cast)
            logger.info(
                'Scenario generated: "%s" | victim=%s | killer=%s | %d clues',
                scenario.title,
                scenario.murder.victim,
                scenario.murder.killer,
                len(scenario.clues),
            )
            return scenario

        except Exception as e:
            if attempt == 0:
                logger.warning("Scenario generation attempt 1 failed: %s — retrying.", e)
                if status_callback:
                    await status_callback("Taking another pass at the scenario...")
                continue
            logger.error("Scenario generation failed after 2 attempts: %s", e)
            raise RuntimeError(f"Failed to generate scenario: {e}") from e

    raise RuntimeError("Scenario generation: unreachable.")
