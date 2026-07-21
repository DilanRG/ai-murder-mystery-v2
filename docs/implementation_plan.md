# AI Murder Mystery Game — Implementation Plan

> **Historical prototype plan:** This plan records the completed real-time v2.0
> prototype and is superseded by [project_brief.md](project_brief.md). The active
> redesign decisions are tracked in [mvp_decisions.md](mvp_decisions.md).

> **Purpose:** Step-by-step build plan with file-level detail.
> Each phase is a self-contained deliverable that can be built in one or two sessions.

---

## Phase 1: Foundation — Story Generation & World State

**Goal:** Generate a complete mystery from character cards and store it in a structured world state.

**Estimated effort:** 1–2 sessions

### Files to Create

#### Backend Core
| File | Purpose |
|---|---|
| `backend/main.py` | FastAPI app skeleton with CORS, lifespan, basic health endpoint |
| `backend/requirements.txt` | Dependencies: fastapi, uvicorn, httpx, pydantic |
| `backend/config/settings.py` | App settings: host, port, LLM config, paths |
| `backend/config/user_settings.py` | User preferences: API key, model, samplers — persisted to JSON |

#### Story Generation
| File | Purpose |
|---|---|
| `backend/story/models.py` | Pydantic/dataclass models: `Scenario`, `MurderDetails`, `Clue`, `LocationDef`, `CharacterBriefing`, `RedHerring` |
| `backend/story/generator.py` | `generate_scenario(characters, player)` — single LLM call with structured output |
| `backend/story/partitioner.py` | `partition_knowledge(scenario)` → dict of agent name → sealed briefing |

#### Character Loading // NOTE: Make sure to update to Character Card V3 Or Do away with Character Cards and shift to a custom json format for efficiency.
| File | Purpose |
|---|---|
| `backend/characters/*.json` | Copy 12 character cards from `game_v1_archive/backend/characters/` |
| `backend/story/characters.py` | `load_characters()`, `select_cast(pool, count=8)`, `Character` dataclass |

#### World State
| File | Purpose |
|---|---|
| `backend/world/state.py` | `WorldState`, `Location`, `CharacterState`, `ClueState` dataclasses |
| `backend/world/event_bus.py` | `EventBus` class with `emit(event)` and subscriber routing by perception rules |

#### LLM Client
| File | Purpose |
|---|---|
| `backend/llm/client.py` | OpenRouter API client — `generate()`, `generate_with_tools()`, tool-calling support |

### API Endpoints (Phase 1)
```
GET  /api/health               → { status, llm_connected }
GET  /api/settings              → current settings
POST /api/settings              → update settings
POST /api/game/new              → create game, generate story, return scenario summary
GET  /api/game/state            → full world state snapshot
```

### Verification
- [ ] Can load all 12 character cards
- [ ] Can select 8, assign roles (killer, victim, 6 innocents)
- [ ] Can generate a complete scenario via LLM
- [ ] Scenario parses into structured models
- [ ] Knowledge partitioning produces per-agent briefings
- [ ] WorldState initializes with locations, characters, and clues

---

## Phase 2: Player Interaction — Movement, Chat & Investigation

**Goal:** Player can move between locations, talk to NPCs, and investigate for clues. No agent autonomy yet — NPCs only respond when spoken to.

**Estimated effort:** 1–2 sessions

### Files to Create / Modify

#### Backend
| File | Purpose |
|---|---|
| `backend/agents/base.py` | `NPCAgent` class with character card, briefing, memory, conversation history |
| `backend/agents/memory.py` | Agent memory model: static knowledge, conversation log, witnessed events, suspicions |
| `backend/agents/manager.py` | `AgentManager` — creates agents from partitioned briefings, handles player→NPC talk |
| `backend/llm/prompt_builder.py` | Build NPC dialogue prompts from character + memory + context |

#### Frontend (Full UI Shell)
| File | Purpose |
|---|---|
| `frontend/index.html` | All screens: title, setup, loading, game, results |
| `frontend/css/styles.css` | Dark noir theme, 3-column game layout, glassmorphism, particles |
| `frontend/js/app.js` | Entry point, initialization |
| `frontend/js/api.js` | REST client + WebSocket connection |
| `frontend/js/screens.js` | Screen navigation with transitions |
| `frontend/js/game.js` | Game screen: map, character list, dialogue, clue journal |
| `frontend/js/settings.js` | Settings modal: API key, model search, samplers | // TODO: Optional 'Service Provider' search, test connection, how much each model costs

#### Vite Setup
| File | Purpose |
|---|---|
| `frontend/package.json` | Vite dev server config |
| `frontend/vite.config.js` | Dev proxy to backend |

### API Endpoints (Phase 2, new)
```
POST /api/game/move             → move player to location
POST /api/game/talk             → talk to NPC (triggers LLM response)
POST /api/game/investigate      → search current location for clues
```

### Verification
- [ ] Frontend loads and shows title screen
- [ ] Can configure settings (API key, model) // NOTE: include the other optional setting and test connection.
- [ ] Can start new game → loading screen → game screen
- [ ] Can move between connected locations on the map
- [ ] Can click NPC → type message → receive AI response in character
- [ ] Investigating reveals clues based on difficulty
- [ ] Clue journal updates as clues are found
- [ ] Event log shows player activity

---

## Phase 3: Agent Autonomy — The Simulation Comes Alive

**Goal:** NPC agents run autonomous loops. They move, talk to each other, investigate, react to events. The world lives.

**Estimated effort:** 2–3 sessions

### Files to Create / Modify

#### Backend
| File | Purpose |
|---|---|
| `backend/agents/base.py` | ADD agent loop: perceive → think → tool_call → cooldown |
| `backend/agents/tools.py` | Tool definitions, execution logic, tool schema for LLM |
| `backend/agents/perception.py` | `get_perception(agent_name)` — filtered world view per perception rules |
| `backend/world/clock.py` | Game clock: none / real-time / event-driven modes |
| `backend/main.py` | ADD WebSocket endpoint `/ws/events` for real-time event streaming |

#### Frontend
| File | Purpose |
|---|---|
| `frontend/js/api.js` | ADD WebSocket client for live events |
| `frontend/js/game.js` | MODIFY: live NPC movement on map, ambient dialogue in event log, NPCs arriving/leaving |

### Agent Loop Behavior
```
For each NPC agent every N seconds (adaptive):
  1. perception = world.get_perception(agent.name)
  2. messages = build_agent_prompt(agent, perception)
  3. response = llm.generate_with_tools(messages, tools)
  4. for tool_call in response.tool_calls:
       event = execute_tool(agent, tool_call)
       event_bus.emit(event)  # routes to affected agents + player
  5. sleep(get_cooldown(agent))
```

### Settings (Player-Configurable)
- NPC Autonomy: Low (mostly idle) / High (active simulation) — default High
- Timer mode: None / Real-time clock (adjustable 15–60 min) / Event-driven

### Verification
- [ ] NPCs move between locations autonomously
- [ ] NPCs talk to each other when in the same location
- [ ] Player can eavesdrop on NPC conversations in their location
- [ ] Events from other locations are NOT shown to the player
- [ ] Killer agent uses plant_evidence / destroy_evidence tools
- [ ] Adaptive tick rate works (faster near activity, slower when idle)
- [ ] WebSocket delivers real-time events to frontend
- [ ] NPC-to-NPC conversation is visible when player is present // NOTE: Not whispered conversations I suppose.

---

## Phase 4: Endgame — Accusation, Results & Polish

**Goal:** Complete game loop. Player can accuse, see results, get debrief. Game ends via timer, accusation, or event.

**Estimated effort:** 1–2 sessions

### Files to Modify

| File | Change |
|---|---|
| `backend/main.py` | ADD `/api/game/accuse`, `/api/game/debrief` endpoints |
| `backend/world/clock.py` | Implement all 3 timer modes, game end conditions |
| `backend/agents/manager.py` | Stop all agent loops on game end |
| `frontend/index.html` | Accusation modal, results screen with debrief tabs |
| `frontend/js/game.js` | Accusation flow, results rendering, debrief tabs |

### Game End Conditions
1. **Player accuses** → check if correct → win/lose
2. **Timer expires** (if real-time mode) → killer escapes → lose
3. **Event-driven climax** → killer attempts to flee → player must act

### Debrief Screen
- Suspects tab: all NPCs with revealed secrets, alibis, true whereabouts
- Evidence tab: all clues (found ✅ / missed ❌), red herrings explained
- Timeline tab: chronological event replay

### Verification
- [ ] Can accuse a suspect → correct answer = win, wrong = lose
- [ ] AI generates a narrative ending
- [ ] Debrief shows complete truth
- [ ] All 3 timer modes work
- [ ] "Play Again" resets everything
- [ ] Game handles edge cases (no agents running, LLM errors)

---

## Phase 5: Distribution — Single-File Executable

**Goal:** Package the game as a single executable for Windows, macOS, and Linux.

**Estimated effort:** 1 session

### Approach
1. Frontend built with `vite build` → static files in `backend/static/`
2. FastAPI serves static files + API
3. PyInstaller bundles Python + FastAPI + static files → single executable
4. On launch: find free port → start server → open browser // NOTE: consider having a dedicated window opening for the game, not the browser.
5. GitHub Actions for cross-platform builds

### Files to Create
| File | Purpose |
|---|---|
| `build/build.py` | Build script: vite build → copy → pyinstaller |
| `build/murder-mystery.spec` | PyInstaller spec file |
| `.github/workflows/release.yml` | CI: build executables for all 3 platforms |
| `backend/launcher.py` | Find port, start server, open browser |

### Verification
- [ ] `python build/build.py` produces a working executable
- [ ] Executable runs on Windows (tested locally)
- [ ] CI produces macOS and Linux builds
- [ ] Single-file launch → browser opens → game works // NOTE: Browser or dedicated window (check if it's movable and resizable).
