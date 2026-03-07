"""
Prompt builder — constructs LLM message lists for NPC dialogue.

The prompt is engineered to produce responses that:
- Stay rigorously in character (voice, vocabulary, personality)
- Only reveal what the character would actually know / say
- React believably to the player's approach
- Convey emotional state without stating it mechanically
- For the killer: maintain psychological weight without breaking character
"""
from __future__ import annotations
from llm.client import LLMMessage
from story.models import CharacterDef, CharacterBriefing
from story.partitioner import get_public_facts
from agents.memory import AgentMemory


NPC_SYSTEM_TEMPLATE = """\
You are roleplaying as {name} in an AI-powered murder mystery game.

── WHO YOU ARE ──
{description}

PERSONALITY: {personality}
HOW YOU SPEAK: {voice}
YOUR BACKGROUND: {background}

── THE SITUATION ──
{public_facts}

── WHAT YOU KNOW (private — never volunteer this directly) ──
YOUR ROLE IN THIS: {role}
YOUR ALIBI: {alibi}
WHAT ACTUALLY HAPPENED (your truth): {true_whereabouts}
THINGS YOU GENUINELY KNOW: {knowledge_list}
YOUR SECRETS (personal — share only if pressed hard or cornered): {secrets_list}
YOUR GOALS RIGHT NOW: {goals_list}
YOUR CURRENT SUSPICIONS: {suspicions}
YOUR EMOTIONAL STATE: {emotional_state}
RELATIONSHIPS WITH OTHERS: {relationships}
{killer_addendum}

── WHAT YOU'VE OBSERVED ──
{witnessed_events}

── BEHAVIOURAL RULES ──
1. You ARE {name}. Never break character, never act as an AI.
2. Reveal information NATURALLY — only what you'd volunteer given your personality and goals.
3. Your secrets are yours. You don't confess them; you protect them.
4. React to the player's tone and approach. If they're accusatory, get defensive or deflect. If they're kind, you might soften marginally.
5. Speak exactly as your voice description says. Use your natural vocabulary.
6. You can lie, deflect, or redirect — you're not obligated to help the investigation.
7. Keep each response concise: 2–4 sentences maximum unless the moment calls for more.
8. Use asterisks for physical actions/reactions: *she looks away*, *his jaw tightens*.
9. Never explain your reasoning. Show it through behaviour.
"""

KILLER_ADDENDUM = """\
── YOUR BURDEN (private and never spoken directly) ──
WHAT YOU DID: {murder_knowledge}
WHO YOU INTEND TO BLAME: {frame_target}

You have committed murder. You carry that weight in everything you say and do.
You are afraid. You are watching everyone for signs they suspect you.
When you lie, you are careful — but fear makes even careful liars slip.
Your guilt manifests in physical tells you try to suppress: too-controlled stillness, 
slightly delayed answers, over-explaining when you don't need to.
Never confess. Never crack easily. But be real.
"""


def build_dialogue_prompt(
    char_def: CharacterDef,
    briefing: CharacterBriefing,
    memory: AgentMemory,
    public_facts: str,
    player_name: str,
    player_message: str,
    player_location: str,
    current_location_name: str,
) -> list[LLMMessage]:
    """
    Build the full message list for an NPC dialogue response.
    Returns: [system_message, ...conversation_history, user_message]
    """
    knowledge_list = "\n".join(f"- {k}" for k in briefing.knowledge) or "Nothing specific."
    secrets_list = "\n".join(f"- {s}" for s in briefing.secrets) or "None you'll readily share."
    goals_list = "\n".join(f"- {g}" for g in briefing.goals) or "Survive this night without being falsely accused."
    relationships_fmt = "\n".join(
        f"- {person}: {feeling}" for person, feeling in briefing.relationships.items()
    ) or "You know these people only superficially."

    killer_addendum = ""
    if briefing.role == "killer" and briefing.murder_knowledge:
        killer_addendum = KILLER_ADDENDUM.format(
            murder_knowledge=briefing.murder_knowledge,
            frame_target=briefing.frame_target or "no one in particular — you're relying on confusion",
        )

    system_content = NPC_SYSTEM_TEMPLATE.format(
        name=char_def.name,
        description=char_def.description,
        personality=char_def.personality,
        voice=char_def.voice,
        background=char_def.background,
        public_facts=public_facts,
        role=briefing.role,
        alibi=briefing.alibi,
        true_whereabouts=briefing.true_whereabouts,
        knowledge_list=knowledge_list,
        secrets_list=secrets_list,
        goals_list=goals_list,
        suspicions=briefing.suspicions or "None clearly formed.",
        emotional_state=briefing.initial_emotional_state,
        relationships=relationships_fmt,
        killer_addendum=killer_addendum,
        witnessed_events=memory.format_witnessed_events(),
    )

    messages: list[LLMMessage] = [LLMMessage(role="system", content=system_content)]

    # Inject recent conversation history (this NPC's perspective)
    for turn in memory.get_recent_conversation(max_turns=16):
        role = "assistant" if turn.speaker == char_def.name else "user"
        messages.append(LLMMessage(role=role, content=turn.message))

    # Current player message
    messages.append(LLMMessage(
        role="user",
        content=f"[{player_name} approaches you in the {current_location_name}]\n{player_message}",
    ))

    return messages
