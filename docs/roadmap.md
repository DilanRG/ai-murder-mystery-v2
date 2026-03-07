# AI Murder Mystery v2 — Roadmap

> **Purpose:** High-level milestone tracker for the project manager.
> Update this document as milestones are completed.
> 
> **Last updated:** 2026-03-06

---

## Project Info

| Field | Value |
|---|---|
| **Project** | AI Murder Mystery v2 |
| **Lead Developer** | Antigravity (architecture, oversight, complex tasks) |
| **Primary Builder** | Claude Sonnet 4.6 (implementation) |
| **Subcontractors** | Gemini 3.1 Pro (as needed) |
| **Project Manager** | Dilan |
| **Repository** | `c:\random scripting\game` (DilanRG/ai-murder-mystery) |
| **v1 Archive** | `c:\random scripting\game_v1_archive` |

---

## Key Documentation

| Document | Path | Purpose |
|---|---|---|
| Architecture | [architecture.md](file:///c:/random%20scripting/game/docs/architecture.md) | Technical reference — system design, agent model, API, conventions |
| Implementation Plan | [implementation_plan.md](file:///c:/random%20scripting/game/docs/implementation_plan.md) | Phase-by-phase build plan with file-level detail |
| Roadmap | [roadmap.md](file:///c:/random%20scripting/game/docs/roadmap.md) | This file — milestone tracker |
| v1 Analysis | [game_analysis_report.md](file:///c:/Users/dilan/.gemini/antigravity/brain/9750cb6e-d995-46a3-97f5-be6e0d86bb38/game_analysis_report.md) | Analysis of v1 for reference |

---

## Milestones

### Phase 1: Foundation — Story Generation & World State ✅
- [x] Backend core (FastAPI, settings, LLM client)
- [x] Character pool — 12 custom JSON characters (custom format, morally grey, diverse walks of life)
- [x] Story generation (single LLM call → full scenario, JSON parse, retry logic)
- [x] Knowledge partitioning (per-agent briefings + public facts)
- [x] World state model (locations, characters, clues, presence index)
- [x] Event bus (emit + route by whisper/normal/shout perception rules)
- [x] Endpoints: health, settings, models (with pricing), new game, state, move, investigate, accuse, debrief
- [x] WebSocket event streaming
- [x] README.md + build-and-run workflow updated for uv
- [x] Python venv created, 24 packages installed via uv

### Phase 2: Player Interaction — Movement, Chat & Investigation ✅
- [x] NPC agent class (`agents/base.py`) with character def, briefing, memory
- [x] Player→NPC conversation via LLM (`agents/manager.py`, `/api/game/talk`)
- [x] Player movement (location graph, `/api/game/move`)
- [x] Investigation (clue discovery, difficulty roll, `/api/game/investigate`)
- [x] Full frontend UI — 5 screens (title, setup, loading, game, results) + 2 modals
- [x] Settings modal (API key, model search with pricing/free flag, test connection, sampler sliders)
- [x] 900-line dark noir CSS design system (glassmorphism, animations, 3-col game layout)
- [x] 5 JS modules (api.js, screens.js, settings.js, game.js, app.js)
- [x] Vite build verified: 8 modules, 109ms, outputs to `backend/static/`
- [x] Bug fixes: `to_client_dict` player inclusion, move event `from` field

### Phase 3: Agent Autonomy — The Simulation ✅
- [x] `agents/perception.py` — filtered per-agent world view with `format_for_prompt()`
- [x] `agents/tools.py` — 7 tools: move_to, speak, whisper, examine, plant_evidence, destroy_evidence, do_nothing
- [x] `world/clock.py` — GameClock with 3 timer modes, adaptive tick rate (10/18/30s)
- [x] `agents/base.py` — Full perceive→think→act loop: staggered startup, LLM tool-calling, world mutation, event emission, idle backoff
- [x] Killer agent gets murder_knowledge + frame_target system prompt addendum
- [x] `agents/manager.py` — `start_all_loops()` / `stop_all_loops()` lifecycle management
- [x] `main.py` — GameClock + agent loops wired into `new_game`, loops stopped on `accuse`
- [x] `NewGameRequest` extended with `timer_mode` + `timer_minutes`
- [x] Phase 3 smoke test passed: 7 tools, GameClock tick rates verified

### Phase 4: Endgame — Accusation, Results & Polish ✅
- [x] Accusation flow — correct/wrong verdict + narrative
- [x] AI-generated narrative ending (LLM-written noir paragraph in `accuse` endpoint)
- [x] `/api/game/end` timeout endpoint for realtime timer expiry
- [x] Post-game debrief — full reveals: suspects (alibi + true whereabouts + secrets), evidence (found/missed/planted), red herrings, timeline
- [x] Timeline tab — chronological event replay from `world.events`, color-coded by type
- [x] Realtime countdown timer (turns red < 2min, auto-calls `/api/game/end` on expiry)
- [x] Setup screen passes `timer_mode` + `timer_minutes` to `newGame()`
- [x] Toast notification system (error/info/success/warning)
- [x] `game_phase` WS handler in `app.js` — handles timeout and narrative on game end
- [x] `showResults` exported from `game.js`, accepts injected debrief (no double-fetch on WS path)
- [x] Planted evidence section in evidence tab
- [x] Play-again reloads page for clean state
- [x] Vite build clean: 8 modules, 0 warnings, 146ms

### Phase 5: Distribution — Single-File Executable ✅
- [x] Vite production build → static files (8 modules, 0 warnings, 110ms)
- [x] PyInstaller packaging → `ai-murder-mystery.exe` (13.4 MB)
- [x] Launcher (find free port 8765–8800 → start uvicorn → open browser)
- [x] Build script with `--clean` and `--skip-frontend` flags
- [x] GitHub Actions CI (Windows, macOS, Linux matrix → auto-release on tags)
- [x] Quality assessment: 8/10 overall rating

---

## Design Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-03-06 | No turn system — continuous real-time | More immersive, agents act naturally |
| 2026-03-06 | Player character NOT from card pool | Player creates their own character |
| 2026-03-06 | 8 cast members: 1 killer, 1 victim, 6 innocent | Balances complexity and API costs |
| 2026-03-06 | Detective role only (v2.0), killer deferred | Focus on core experience first |
| 2026-03-06 | Adaptive agent tick rate (5–30 sec) | Balances responsiveness and API cost |
| 2026-03-06 | Vite + vanilla JS frontend | Lightweight, cross-platform via browser |
| 2026-03-06 | Single-file executable distribution | User requirement — no command-line setup |
| 2026-03-06 | All 3 timer modes available to player | Player choice: none, real-time, event-driven |
| 2026-03-06 | Agent autonomy: Low/High, default High | Player can choose level of NPC activity |
| 2026-03-06 | OpenRouter with free model support | Cost flexibility — DeepSeek R1 etc. |

---

## Session Log

| Date | Session | Agent | Work Done |
|---|---|---|---|
| 2026-03-06 | #1 | Antigravity | Analyzed v1 codebase, archived to `game_v1_archive/`, designed v2 architecture, created architectural docs + implementation plan + roadmap, cleaned project directory |
| 2026-03-06 | #2 | Antigravity | Phase 1 complete: 12 custom character JSONs, story generator (full prompt + JSON parse + retry), LLM client (tool-calling + model fetch with pricing), world state + event bus, all FastAPI endpoints, WebSocket streaming, venv setup with uv |
| 2026-03-07 | #3 | Antigravity | Phase 2 complete: agents (memory/base/manager), NPC prompt builder (killer psyche addendum), /api/game/talk endpoint, full Vite frontend (5 screens, 2 modals, 900-line noir CSS, 5 JS modules), npm + vite build verified |
| 2026-03-07 | #4 | Antigravity | Phase 2 verification + Phase 3 complete: fixed to_client_dict + move event bugs; built perception.py, tools.py (7 tools), clock.py (3 timer modes, adaptive tick), extended base.py with full autonomous loop (killer psyche, staggered startup, idle backoff), updated manager.py + main.py lifecycle wiring |
| 2026-03-07 | #5 | Antigravity | Phase 4 complete: AI narrative ending on accuse, /api/game/end timeout endpoint, debrief timeline from world.events, event_bus WS format fixed, timer countdown in frontend (turns red <2min), verdict-narrative element, 4th debrief tab (Timeline), planted evidence section, play-again reload, toast notification system, Vite build clean 8 modules 0 warnings |


---

## Design Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-03-06 | No turn system — continuous real-time | More immersive, agents act naturally |
| 2026-03-06 | Player character NOT from card pool | Player creates their own character |
| 2026-03-06 | 8 cast members: 1 killer, 1 victim, 6 innocent | Balances complexity and API costs |
| 2026-03-06 | Detective role only (v2.0), killer deferred | Focus on core experience first |
| 2026-03-06 | Adaptive agent tick rate (5–30 sec) | Balances responsiveness and API cost |
| 2026-03-06 | Vite + vanilla JS frontend | Lightweight, cross-platform via browser |
| 2026-03-06 | Single-file executable distribution | User requirement — no command-line setup |
| 2026-03-06 | All 3 timer modes available to player | Player choice: none, real-time, event-driven |
| 2026-03-06 | Agent autonomy: Low/High, default High | Player can choose level of NPC activity |
| 2026-03-06 | OpenRouter with free model support | Cost flexibility — DeepSeek R1 etc. |

---

## Session Log

| Date | Session | Agent | Work Done |
|---|---|---|---|
| 2026-03-06 | #1 | Antigravity | Analyzed v1 codebase, archived to `game_v1_archive/`, designed v2 architecture, created architectural docs + implementation plan + roadmap, cleaned project directory |
| 2026-03-06 | #2 | Antigravity | Phase 1 complete: 12 custom character JSONs, story generator (full prompt + JSON parse + retry), LLM client (tool-calling + model fetch with pricing), world state + event bus, all FastAPI endpoints, WebSocket streaming, venv setup with uv |
| 2026-03-07 | #3 | Antigravity | Phase 2 complete: agents (memory/base/manager), NPC prompt builder (killer psyche addendum), /api/game/talk endpoint, full Vite frontend (5 screens, 2 modals, 900-line noir CSS, 5 JS modules), npm + vite build verified |
| 2026-03-07 | #4 | Antigravity | Phase 2 verification + Phase 3 complete: fixed to_client_dict + move event bugs; built perception.py, tools.py (7 tools), clock.py (3 timer modes, adaptive tick), extended base.py with full autonomous loop (killer psyche, staggered startup, idle backoff), updated manager.py + main.py lifecycle wiring |
| 2026-03-07 | #5 | Antigravity | Phase 4 complete: AI narrative ending on accuse, /api/game/end timeout, debrief timeline from world.events, event_bus WS format fixed, timer countdown, verdict-narrative, Timeline tab, planted evidence, play-again reload, toast notifications |
| 2026-03-07 | #6 | Antigravity | Phase 5 complete + quality assessment: launcher.py, build/build.py, murder-mystery.spec, release.yml. Full build verified: 13.4MB exe. Codebase rated 8/10 with recommendations for v2.1 |
