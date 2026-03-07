"""
Character card loader.
Reads from backend/characters/*.json (custom format).
"""
import json
import logging
import random
from pathlib import Path

from story.models import CharacterDef
from config.settings import CHARACTERS_DIR

logger = logging.getLogger(__name__)


def load_all_characters() -> list[CharacterDef]:
    """Load all character definitions from the characters directory."""
    characters: list[CharacterDef] = []
    for path in sorted(CHARACTERS_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            characters.append(CharacterDef(**data))
            logger.debug("Loaded character: %s", data.get("name", path.stem))
        except Exception as e:
            logger.error("Failed to load character %s: %s", path.name, e)
    logger.info("Loaded %d characters from pool.", len(characters))
    return characters


def select_cast(pool: list[CharacterDef], count: int = 8) -> list[CharacterDef]:
    """
    Randomly select `count` characters from the pool.
    Ensures variety by not selecting characters with the same possible role set.
    """
    if len(pool) < count:
        raise ValueError(f"Need at least {count} characters, only {len(pool)} available.")
    # Prefer diverse possible_roles coverage
    victims = [c for c in pool if "victim" in c.possible_roles]
    killers = [c for c in pool if "killer" in c.possible_roles]
    rest = [c for c in pool if c not in victims and c not in killers]
    random.shuffle(victims)
    random.shuffle(killers)
    random.shuffle(rest)
    # Guarantee at least one potential victim and one potential killer in cast
    selected: list[CharacterDef] = []
    if victims:
        selected.append(victims.pop(0))
    if killers:
        selected.append(killers.pop(0))
    remaining_pool = victims + killers + rest
    random.shuffle(remaining_pool)
    while len(selected) < count and remaining_pool:
        selected.append(remaining_pool.pop(0))
    random.shuffle(selected)  # Shuffle final cast order
    logger.info("Selected cast: %s", [c.name for c in selected])
    return selected
