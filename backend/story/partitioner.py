"""Knowledge partitioning — splits the generated scenario into per-agent briefings."""
import logging
from story.models import Scenario, CharacterBriefing

logger = logging.getLogger(__name__)


def partition_knowledge(scenario: Scenario) -> dict[str, CharacterBriefing]:
    """
    Return scenario.character_briefings as-is (they were populated by the generator).
    This function is a hook for future transformations (e.g. redacting info from briefings
    based on difficulty, or injecting misinformation for Hard mode).
    """
    briefings = scenario.character_briefings
    logger.info("Knowledge partitioned for %d agents.", len(briefings))
    return briefings


def get_public_facts(scenario: Scenario) -> str:
    """
    Return the facts every agent knows publicly:
    victim identity, setting, location names, and that a murder occurred.
    Used as the shared prefix in every agent's system prompt.
    """
    loc_list = ", ".join(f"{loc.name}" for loc in scenario.locations)
    return (
        f"SETTING: {scenario.setting}\n"
        f"A murder has occurred. The victim is {scenario.murder.victim}.\n"
        f"Time of death: {scenario.murder.time_of_death}.\n"
        f"Known locations in this place: {loc_list}.\n"
        f"Background: {scenario.backstory}"
    )
