# AI Murder Mystery v2

A **single-player, AI-driven murder mystery game** where autonomous NPC agents live in a continuous simulated world. Interrogate suspects, find evidence, and accuse the killer before time runs out, while the NPCs are actively scheming against you.

---

## Gameplay

You play as a detective investigating a murder. The other 7 characters (including the killer) live in the game world in real time — they move between rooms, talk to each other, plant or destroy evidence, and generally try to survive investigation. The killer knows who they are, and will act accordingly.

- **Chat with NPCs** to gather information
- **Investigate locations** to find physical clues
- **Watch the event log** — NPC movements and conversations are visible
- **Accuse** when you're confident — wrong accusation ends the game

---

## Quick Start (Development)

### Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- Node.js 18+
- An [OpenRouter](https://openrouter.ai) API key *(free tier works)*

### 1. Install dependencies
```bash
# Backend
uv venv backend/.venv
uv pip install -r backend/requirements.txt --python backend/.venv/Scripts/python.exe

# Frontend
cd frontend && npm install
```

### 2. Start the backend
```bash
cd backend
uv run uvicorn main:app --host 127.0.0.1 --port 8765 --reload
```

### 3. Start the Vite dev server (second terminal)
```bash
cd frontend && npm run dev
# Open http://localhost:5173
```

---

## Production Build (Single Executable)

```bash
python build/build.py
# Output: dist/ai-murder-mystery.exe  (~13 MB)
```

The executable bundles FastAPI + the Vite-built frontend. On launch it finds a free port, starts the server, and opens your browser automatically.

```bash
# Options
python build/build.py --clean          # Clean dist/ and build/ first
python build/build.py --skip-frontend  # Skip Vite build (use existing static/)
```

---

## Running Tests

```bash
cd backend
uv run pytest tests/ -v
```

---

## Architecture

```
game/
├── backend/                 # FastAPI server
│   ├── main.py              # Endpoints: /api/game/*, /api/settings, WebSocket
│   ├── launcher.py          # Executable entry point
│   ├── agents/              # NPC autonomous agents (perceive → think → act)
│   │   ├── base.py          # NPCAgent: LLM tool-call loop
│   │   ├── manager.py       # Start/stop all agent loops
│   │   ├── memory.py        # Short-term NPC memory
│   │   ├── perception.py    # Filtered world view per agent
│   │   └── tools.py         # 7 tools: move, speak, whisper, examine, plant, destroy, do_nothing
│   ├── world/               # Game world
│   │   ├── state.py         # WorldState: ground truth, all mutations
│   │   ├── event_bus.py     # Event emission → WebSocket broadcast
│   │   └── clock.py         # Timer: none / realtime countdown / event-driven
│   ├── story/               # Story generation
│   │   ├── generator.py     # LLM prompt → full mystery scenario (JSON)
│   │   ├── models.py        # Pydantic models: Scenario, LocationDef, ClueDef, etc.
│   │   ├── characters.py    # Load character pool from JSON files
│   │   └── partitioner.py   # Split scenario into per-NPC knowledge briefings
│   ├── llm/                 # LLM client
│   │   ├── client.py        # OpenRouter API wrapper (standard + tool-calling)
│   │   └── prompt_builder.py # NPC system prompt construction
│   ├── config/              # Configuration
│   │   ├── settings.py      # App constants (paths, defaults)
│   │   └── user_settings.py # User config persistence (API key, model, etc.)
│   ├── characters/          # Character card pool (12 JSON files)
│   └── tests/               # pytest suite
│       ├── test_world.py    # WorldState mutations and queries
│       ├── test_tools.py    # Agent tool execution
│       └── test_event_bus.py # Event recording and broadcast
├── frontend/                # Vite + vanilla JS (built → backend/static/)
│   ├── index.html           # 5 screens: title, setup, loading, game, results
│   ├── css/styles.css       # 1180-line noir design system
│   └── js/
│       ├── app.js           # Screen orchestration, WS, toast notifications
│       ├── game.js          # Map, chat feed, timer, debrief (4 tabs)
│       ├── api.js           # fetch/WebSocket wrapper
│       ├── settings.js      # Model search, sampler controls
│       └── screens.js       # Screen transition logic
├── build/                   # Build system
│   ├── build.py             # Orchestrator: Vite → PyInstaller
│   └── murder-mystery.spec  # PyInstaller bundle config
├── docs/                    # Documentation
│   ├── architecture.md
│   ├── implementation_plan.md
│   └── roadmap.md
└── .github/workflows/
    └── release.yml          # CI: build Win/Mac/Linux on version tags
```

---

## Roadmap

All 5 phases complete as of v2.0:

| Phase | Status | Description |
|---|---|---|
| 1 | ✅ | Story generation, LLM client, world state, FastAPI endpoints |
| 2 | ✅ | NPC agents, dialogue, frontend (5 screens, noir CSS) |
| 3 | ✅ | Autonomous agent loops (perceive-think-act), game clock |
| 4 | ✅ | Accusation + AI narrative ending, debrief + timeline, game over |
| 5 | ✅ | Single-file executable, GitHub Actions CI |

See [`docs/roadmap.md`](docs/roadmap.md) for detailed milestone tracking.

---

## Configuration

Settings are persisted in `user_config.json` (gitignored). The most important ones:

| Setting | Default | Description |
|---|---|---|
| API Key | *(required)* | OpenRouter API key |
| Model | `deepseek/deepseek-r1:free` | Any OpenRouter-hosted model |
| Timer Mode | `none` | `none` / `realtime` / `event` |
| Timer Minutes | 30 | Used when `timer_mode=realtime` |
| Difficulty | `normal` | `easy` / `normal` / `hard` |
