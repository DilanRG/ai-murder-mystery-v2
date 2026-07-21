# AI Murder Mystery Game — Technical Architecture

> **Archived prototype document:** This describes the superseded real-time v2.0
> prototype. It is not the architecture of the active build. Current invariant
> boundaries are in [product_north_star.md](product_north_star.md), current systems
> direction is in [AI_Murder_Mystery_Game_Design_Roadmap.md](AI_Murder_Mystery_Game_Design_Roadmap.md),
> settled choices are in [decision_log.md](decision_log.md), and verified reality is
> in [active_status.md](active_status.md).

> **Historical purpose:** Retain the prototype's original technical design for
> archaeology and regression context. Statements below such as “continuous, not
> turn-based” are historical, not active requirements.

---

## 1. Project Overview

An AI-powered murder mystery game where **8 NPC agents** powered by LLMs inhabit a procedurally
generated mystery. Unlike v1 (turn-based with prompt templates), v2 uses **continuous real-time
simulation** with tool-calling agents. The player acts as a detective investigating a murder while
AI agents autonomously move, talk, investigate, and react around them.

### Key Principles
- **Story-first:** A complete mystery is pre-generated, then partitioned among agents
- **Continuous, not turn-based:** No turn counter. Player acts freely, agents tick on adaptive timers
- **Tool-calling agents:** NPCs interact with the world through a defined tool schema — no freeform state mutation
- **Perception-based:** Agents only know what their character could naturally observe
- **Single-file distribution:** Final product must be a single executable for Windows, macOS, and Linux

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        PLAYER (Browser)                         │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  Game UI     │  │  Chat Panel  │  │  Map / Clue Journal    │  │
│  │  (Vite + JS) │  │  (WebSocket) │  │  (WebSocket updates)   │  │
│  └──────┬───── ┘  └──────┬───────┘  └───────────┬────────────┘  │
│         │   REST actions  │  WS events           │               │
└─────────┼─────────────────┼──────────────────────┼───────────────┘
          │                 │                      │
          ▼                 ▼                      ▼
┌──────────────────────────────────────────────────────────────────┐
│                     BACKEND (Python FastAPI)                      │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │  REST API     │  │  WebSocket   │  │  Story Generator        │ │
│  │  (player      │  │  Manager     │  │  (single LLM call       │ │
│  │   actions)    │  │  (event      │  │   → complete mystery)   │ │
│  │              │  │   broadcast)  │  │                         │ │
│  └──────┬───────┘  └──────┬───────┘  └─────────────────────────┘ │
│         │                 │                                       │
│         ▼                 ▼                                       │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │                    WORLD STATE (in-memory)                 │   │
│  │                                                            │   │
│  │  locations: Map<id, Location>                              │   │
│  │  characters: Map<name, CharacterState>                     │   │
│  │  clues: Map<id, ClueState>                                 │   │
│  │  events: Event[]  (append-only log)                        │   │
│  │  conversations: Conversation[]                             │   │
│  │  game_clock: float  (elapsed seconds)                      │   │
│  └────────────────────────┬───────────────────────────────────┘   │
│                           │                                       │
│         ┌─────────────────┼─────────────────────┐                 │
│         ▼                 ▼                     ▼                 │
│  ┌─────────────┐  ┌─────────────┐       ┌─────────────┐          │
│  │  Agent 1     │  │  Agent 2    │  ...  │  Agent 8    │          │
│  │  (NPC Loop)  │  │  (NPC Loop) │       │  (NPC Loop) │          │
│  │              │  │             │       │             │          │
│  │  perceive → │  │  perceive → │       │  perceive → │          │
│  │  think    → │  │  think    → │       │  think    → │          │
│  │  tool_call  │  │  tool_call  │       │  tool_call  │          │
│  └─────────────┘  └─────────────┘       └─────────────┘          │
│         │                 │                     │                 │
│         └─────────────────┼─────────────────────┘                 │
│                           ▼                                       │
│                   ┌───────────────┐                                │
│                   │  Event Bus    │                                │
│                   │  (routes      │                                │
│                   │   events to   │                                │
│                   │   agents +    │                                │
│                   │   player)     │                                │
│                   └───────────────┘                                │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │                    LLM CLIENT (OpenRouter)                 │   │
│  │  - Tool calling support                                    │   │
│  │  - Model selection (incl. free models like DeepSeek R1)    │   │
│  │  - Rate limiting / cost tracking                           │   │
│  └────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

---

## 3. Cast & Story Generation

### 3.1 Character Pool
- **12 Character Card V2 files** in `backend/characters/*.json` // TODO: update to Character Card V3
- Each card: name, description, personality, first_mes, mes_example, tags, secrets, social_connections, possible_roles, default_location // NOTE: Should be morally ambiguous and grey characters that are complex and have depth. Unique characters from all walks of life.
- Cards are carried over from v1 (stored in `game_v1_archive/backend/characters/`)

### 3.2 Cast Selection (per game)
```
Pool of 12 → randomly select 8:
  • 1 Killer    (NPC agent)
  • 1 Victim    (dead before game starts — not an agent)
  • 6 Innocent  (NPC agents — suspects, witnesses, red herrings)

Player creates their own character (NOT from the card pool):
  • Name, description, role = detective (killer role deferred to later)
```

### 3.3 Story Generation
A single structured LLM call with all 8 character cards produces:

| Output | Description |
|---|---|
| `setting` | Location, time period, atmosphere |
| `murder` | Victim, killer, method, motive, time/place of death |
| `locations[]` | 5–8 interconnected rooms/areas with descriptions |
| `clues[]` | 6–10 clues with difficulty tiers, locations, what they implicate |
| `red_herrings[]` | 2–4 false leads |
| `character_briefings{}` | Per-NPC: alibi, truth, knowledge, secrets, goals, relationships, emotional state, suspicions |
| `opening_narration` | Atmospheric intro text |

### 3.4 Knowledge Partitioning
After generation, each agent receives ONLY:
- Their character card (personality, description)
- Their briefing (alibi, secrets, goals, relationships)
- Public world facts (victim identity, setting, location names)
- Their `first_mes` as behavioral template

Agents do NOT receive: other agents' briefings, full clue list, murder details (except killer).

---

## 4. Agent System

### 4.1 Agent Loop
Each NPC agent runs an async loop:

```python
async def agent_loop(agent: NPCAgent):
    while game.is_running:
        # 1. Gather perception
        perception = world.get_perception(agent.name)
        
        # 2. Build prompt with character + memory + perception
        messages = build_agent_prompt(agent, perception)
        
        # 3. LLM call with tools
        response = await llm.generate_with_tools(messages, agent.tools)
        
        # 4. Execute tool calls → produce events
        for tool_call in response.tool_calls:
            event = await execute_tool(agent, tool_call)
            event_bus.emit(event)
        
        # 5. Adaptive cooldown
        await asyncio.sleep(agent.get_cooldown())
```

### 4.2 Agent Tools

| Tool | Parameters | Returns | Who Can Use |
|---|---|---|---|
| `move_to` | `location_id` | success, description, characters_here | All agents |
| `say` | `message`, `volume: normal\|whisper\|shout` | heard_by[] | All agents |
| `say_to` | `target_name`, `message` | response_queued | All agents |
| `look_around` | — | location, characters, objects, atmosphere | All agents |
| `examine` | `target` | description, clue_found? | All agents |
| `update_suspicion` | `target`, `level`, `reason` | — | All agents |
| `update_emotional_state` | `state` | — | All agents |
| `plant_evidence` | `location`, `description`, `frame_target` | success | Killer only |
| `destroy_evidence` | `clue_id` | success | Killer only |

### 4.3 Perception Model
Agents perceive through a filtered world view:

```
CAN perceive:
  ✅ Characters in the same location
  ✅ Normal/shout speech in same location  
  ✅ Shout speech from adjacent locations (faintly)
  ✅ Characters entering/leaving their location
  ✅ Objects and clues at their location

CANNOT perceive:
  ❌ Events in non-adjacent locations
  ❌ Whispered conversations they're not in
  ❌ Other agents' internal states
  ❌ Full murder solution (unless killer)
```

### 4.4 Adaptive Tick Rate
```python
def get_cooldown(self) -> float:
    if self.pending_events:     return 5.0    # Something just happened
    if self.in_conversation:    return 3.0    # Active dialogue  
    if self.player_nearby:      return 8.0    # Show activity near player
    if self.autonomy == "high": return 15.0   # Background activity
    return 30.0                               # Idle
```

### 4.5 Agent Memory
Each agent maintains:
- **Static:** Character card + briefing (immutable)
- **Conversation log:** All dialogue they've participated in or overheard
- **Witnessed events:** Events perceived through the event bus
- **Suspicions:** Map of other characters → suspicion level + reasoning
- **Emotional state:** Current mood (nervous, calm, angry, etc.)

---

## 5. World State

### 5.1 Core State Model
```python
@dataclass
class WorldState:
    locations: dict[str, Location]           # id → Location
    characters: dict[str, CharacterState]    # name → CharacterState
    clues: dict[str, ClueState]              # id → ClueState
    events: list[GameEvent]                  # append-only event log
    conversations: list[Conversation]         # all dialogue records
    game_clock: float                         # elapsed seconds
    game_phase: GamePhase                     # setup | playing | ended
    
@dataclass
class Location:
    id: str
    name: str
    description: str
    connected_to: list[str]
    characters_present: set[str]
    clues_here: set[str]

@dataclass  
class CharacterState:
    name: str
    location: str
    alive: bool
    role: str                    # killer, suspect, witness, victim
    emotional_state: str
    suspicions: dict[str, int]   # name → 0-100

@dataclass
class ClueState:
    id: str
    description: str
    location: str
    points_to: str
    difficulty: str              # easy, medium, hard
    discovered: bool
    discovered_by: str | None
    planted: bool                # was this planted by the killer?
```

### 5.2 Event Bus
```python
@dataclass
class GameEvent:
    timestamp: float
    event_type: str              # movement, speech, discovery, observation
    actor: str                   # who caused it
    location: str
    description: str
    visible_to: list[str]        # which characters can perceive this
    data: dict                   # type-specific payload
```

Events route based on perception rules (§4.3). The frontend receives events via WebSocket.

---

## 6. Player Interface

### 6.1 Player Actions (REST API)
| Endpoint | Method | Description |
|---|---|---|
| `POST /api/game/new` | Create game | Select characters, generate story |
| `POST /api/game/move` | Move player | Instant location change |
| `POST /api/game/talk` | Talk to NPC | Triggers agent response (priority) |
| `POST /api/game/investigate` | Search area | Check for clues at location |
| `POST /api/game/accuse` | Accuse suspect | Ends the game |
| `GET /api/game/state` | Full state | Current world state snapshot |
| `GET /api/settings` | Settings | Model, API key, preferences |
| `POST /api/settings` | Update settings | Save preferences |

### 6.2 Real-Time Events (WebSocket)
```
ws://localhost:PORT/ws/events

Server → Client messages:
  { type: "npc_moved",    data: { who, from, to } }
  { type: "npc_spoke",    data: { who, message, volume, location } }
  { type: "npc_arrived",  data: { who, location } }
  { type: "npc_left",     data: { who, location } }
  { type: "clue_found",   data: { clue_id, description, found_by } }
  { type: "atmosphere",   data: { text } }
  { type: "game_phase",   data: { phase, reason } }
```

### 6.3 Game Settings (Player-Configurable) // TODO: describe how these settings affect the game play (and associated costs if any)
| Setting | Options | Default |
|---|---|---|
| Timer model | None / Real-time clock / Event-driven | Event-driven |
| Clock duration | 15–60 minutes (if real-time) | 30 min |
| NPC autonomy | Low / High | High |
| LLM model | Any OpenRouter model | User's choice |
| Difficulty | Easy / Normal / Hard | Normal |

---

## 7. Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Vite + vanilla JS + CSS | No framework. Premium dark noir UI |
| Backend | Python 3.11+ FastAPI | Async, WebSocket support |
| Agent runtime | Custom async loops | No LangChain — lightweight tool-calling |
| LLM | OpenRouter API | Supports free models (DeepSeek R1) |
| State | In-memory Python dataclasses | No database needed |
| Distribution | PyInstaller (backend) + embedded frontend | Single executable per platform |
| Build | GitHub Actions CI | Win/macOS/Linux |

### 7.1 Distribution Model
The final product must be a **single executable** that:
1. Starts the FastAPI backend on a random available port
2. Opens the default browser to `http://localhost:{port}`
3. Serves the frontend as static files from the FastAPI server
4. Runs on Windows, macOS, and Linux

---

## 8. Directory Structure
```
game/
├── .agent/workflows/          # Agent workflows (build-and-run, etc.)
├── docs/                      # This architecture doc + roadmap
│   ├── architecture.md        # ← THIS FILE
│   ├── implementation_plan.md # Phase-by-phase build plan
│   └── roadmap.md             # Milestone tracker
├── backend/
│   ├── main.py                # FastAPI app, REST + WebSocket endpoints
│   ├── requirements.txt
│   ├── characters/            # Character Card V2 JSON files /TODO: update to character card v3
│   ├── config/
│   │   ├── settings.py        # App settings
│   │   └── user_settings.py   # Persisted user preferences
│   ├── story/
│   │   ├── generator.py       # LLM story generation
│   │   ├── models.py          # Story data models (scenario, murder, clues)
│   │   └── partitioner.py     # Knowledge partitioning per agent
│   ├── world/
│   │   ├── state.py           # WorldState, Location, CharacterState, ClueState
│   │   ├── event_bus.py       # Event routing + perception filtering
│   │   └── clock.py           # Game clock + timer modes
│   ├── agents/
│   │   ├── base.py            # NPCAgent base class + loop
│   │   ├── tools.py           # Tool definitions + execution
│   │   ├── perception.py      # Perception gathering
│   │   ├── memory.py          # Agent memory model
│   │   └── manager.py         # Agent lifecycle management
│   └── llm/
│       ├── client.py          # OpenRouter API client with tool calling
│       └── prompt_builder.py  # Agent prompt construction // NOTE: Make sure the murderer agent knows the gravity of it's actions and the severity of the consequences (if found out).
├── frontend/
│   ├── index.html
│   ├── css/
│   │   └── styles.css
│   └── js/
│       ├── app.js             # Entry point
│       ├── api.js             # REST + WebSocket client
│       ├── screens.js         # Screen navigation
│       ├── game.js            # Game screen logic
│       └── settings.js        # Settings modal
├── .gitignore
└── README.md
```

---

## 9. Conventions for Contributing Agents

> [!IMPORTANT]
> This project is built across multiple sessions by different AI agents.
> Follow these conventions to maintain consistency.

### 9.1 Code Style
- **Python:** PEP 8, type hints everywhere, dataclasses over dicts, async/await
- **JavaScript:** ES modules, `const`/`let` (no `var`), vanilla DOM — no frameworks
- **CSS:** CSS custom properties for theming, BEM-like class naming

### 9.2 Documentation
- Update `docs/roadmap.md` when completing milestones
- Update this architecture doc if you change any fundamental design
- Add docstrings to all Python functions and classes
- Comment non-obvious JavaScript

### 9.3 Testing
- Use Python's `pytest` for backend testing
- Test story generation with mock LLM responses
- Test agent tools independently from the LLM

### 9.4 Git Workflow
- Commit after each completed phase milestone
- Use descriptive commit messages: `feat: phase-1 story generation pipeline`
- Don't commit `venv/`, `node_modules/`, `dist/`, `__pycache__/`
