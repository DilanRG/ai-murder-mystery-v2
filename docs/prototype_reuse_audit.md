# Prototype Reuse Audit

**Status:** Historical audit completed before the turn-based redesign
**Specification at the time:** [project_brief.md](project_brief.md)

Current direction is controlled by [product_north_star.md](product_north_star.md) and [AI_Murder_Mystery_Game_Design_Roadmap.md](AI_Murder_Mystery_Game_Design_Roadmap.md); current settled choices are recorded in [decision_log.md](decision_log.md). This audit remains useful evidence about what was retained or replaced, but it is not an active architecture specification.

## Executive Summary

The repository is a coherent proof of concept, but it implements the opposite simulation model from the new brief: real-time autonomous agents inside a freely LLM-generated world. The safest approach is an incremental replacement behind the existing FastAPI/Vite application boundary. Reusing the web/build shell while replacing the case, state, turn, and visibility domains avoids both a risky full deletion and accidental dependence on invalid prototype assumptions.

## Safe to Reuse

| Area | Reuse decision | Notes |
|---|---|---|
| FastAPI application shell | Reuse and refactor | Lifespan, router separation, loopback hosting, and static serving remain useful. |
| Vite + vanilla JavaScript | Reuse | Meets the responsive web-first requirement without creating a separate desktop client. |
| Noir visual language | Reuse selectively | Palette, typography, panels, transitions, and general atmosphere align with the brief. |
| OpenRouter HTTP client | Adapt behind an interface | Transport, model listing, and sampler support are reusable; world-authoring prompts are not. |
| Character prose | Migrate | Personalities, voices, backgrounds, and example dialogue are strong raw material for eight validated game cards. |
| PyInstaller/GitHub Actions | Defer, then adapt | Useful after the web vertical slice and persistence paths are reliable. |
| Unit-test conventions | Reuse | The current small pytest suite is a useful foundation, but coverage must expand to case validation and full turns. |

## Replace or Retire

| Prototype component | Why it conflicts | Replacement |
|---|---|---|
| Freeform LLM story generation | The LLM invents rooms, facts, clues, alibis, and the solution without structural validation. | Structured location package + deterministic case assembly + validator. |
| Continuous agent loops | Explicitly out of MVP scope; costly and difficult to reproduce or validate. | One player action followed by a deterministic, batched NPC phase. |
| Current `WorldState` | Mixes truth, player-visible state, character state, and discovery flags. | Separate immutable case truth, mutable runtime, per-character knowledge/beliefs, statements, and player notebook. |
| Current event bus queues | Agents are never registered with the queues, so witnessed-event memory is not actually fed by world events. | Deterministic turn event resolver and scoped observation delivery. |
| Current WebSocket event flow | Client handlers receive an envelope but read event fields from the wrong level; movement also leaves client state stale. | Turn-result payloads as the authoritative UI update, with optional notifications later. |
| Character `default_location` use | Generated map IDs are unrelated to static card defaults, often leaving characters outside the map. | Case overlays assign valid starting rooms from the selected location package. |
| Current clue discovery flags | NPC-destroyed clues are marked `discovered`, and the client serializer exposes all discovered clues, including hidden ones. | Separate evidence location/state from player discovery records. |
| Client serialization | Reveals every character location, emotional state, clue target, and red-herring flag regardless of player knowledge. | Dedicated player-view projection based only on legitimate observations. |
| Tool-calling autonomy | Tools constrain mutation, but prompts still see insufficiently separated state and actions occur without a turn plan. | Typed action intents validated and resolved by the turn engine. |
| Timer modes | Event-driven mode has no climax implementation; real-time timeout broadcasts before authoritative state ends. | In-game turn clock for MVP. |
| Dialogue prompt history | The newest player message is inserted twice. | Explicit interview session transcript with bounded exchanges. |
| Settings persistence in packaged builds | The config path resolves inside PyInstaller's temporary extraction directory. | User data directory selected per platform, implemented after web persistence. |

## Prototype Verification Baseline

- All 12 prototype character JSON files load.
- Existing backend suite: 20 tests pass with one event-loop deprecation warning.
- All frontend JavaScript files pass syntax checks.
- The worktree was clean before redesign work began.
- The baseline commit is `cc959627b62259c38bfe9ebb9dc35e459637e419`.

## Migration Strategy

1. Add new typed domain modules and deterministic content alongside the prototype.
2. Prove a complete case through domain tests before changing the frontend.
3. Switch API routers to the turn engine and player-view projection.
4. Rebuild the UI around returned turn results and notebook data.
5. Add constrained dialogue only after deterministic play can reach a valid ending.
6. Remove obsolete real-time modules only when no runtime imports depend on them and a replacement checkpoint is already pushed.

This strategy keeps every checkpoint runnable and makes rollback possible without destructive source replacement.
