# MVP Decision Register

**Status:** Working defaults, surfaced before implementation
**Last updated:** 2026-07-21

The project brief intentionally leaves the following decisions open. These defaults are selected to keep an unattended, iterative build moving while remaining easy to revise. They are not silent assumptions; the project owner may override any item.

| Decision | Working MVP default | Rationale and boundary |
|---|---|---|
| First location | **Ashwick Manor**, an isolated country estate cut off by a flooded causeway | Reuses the strongest existing character hooks and noir visual language. It will be a structured package, not an LLM-created map. |
| Turn duration | **10 in-game minutes** per committed investigation action | Readable clock arithmetic and enough turns for an evening investigation. Pure notebook review is free. |
| Action economy | Move, search, examine, or begin an interview commits one turn. An interview permits up to **three exchanges** before its single NPC phase resolves. | Prevents each chat message consuming a turn while bounding context and abuse. |
| Technical stack | Python 3.12+, FastAPI, Pydantic v2, vanilla ES modules, Vite, CSS | It is already present, web-first, lightweight, and compatible with later PWA/hosting/executable delivery. Domain code must remain transport-independent. |
| Hosting model | **Local-first but host-compatible** | No database is required for the first slice; file saves live in a configurable data directory. Avoid assumptions that prevent hosted sessions later. |
| LLM providers | **OpenRouter first**, behind a provider-neutral interface | Reuses existing work. The deterministic game remains fully playable without an API key; LLM use enhances portrayal rather than correctness. |
| NPC batching | Gather seven typed intents from immutable turn-start views, then resolve them in deterministic initiative order | Prevents later NPCs from reasoning against partially mutated state and makes replay/testing reproducible. |
| Accusation scoring | Culprit is mandatory; method, motive, and timeline anchors contribute supporting score. Full win requires the correct culprit plus at least two supporting components. | Rewards actual deduction while preserving a clear result. Exact UI wording can evolve after playtests. |
| Portrait pipeline | Versioned portrait/expression paths with polished placeholders first | Avoids blocking the engine on art. Asset generation/import can replace placeholders without schema changes. |
| Murderer evidence manipulation | May move, conceal, or attempt to destroy only existing evidence explicitly marked manipulable, and only if validator-confirmed redundant solution paths remain | The murderer cannot invent evidence or make the case unsolvable. Planting new evidence is deferred. |
| CCv3 scope | JSON import/export following the [Character Card V3 specification](https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md), plus `extensions.murder_mystery`; PNG/CHARX embedding is deferred | Preserves practical compatibility without making asset-container tooling a vertical-slice blocker. Imported prompts never outrank global rules. |

## Derived Implementation Rules

1. Randomness is seedable and the seed is stored in the save file.
2. The deterministic sample case contains no LLM calls.
3. Every player-facing response is produced by a player-view projector; API routes never serialize internal case objects directly.
4. Every state-changing request is a typed intent validated by the engine.
5. Immutable case truth is frozen after validation.
6. Save files include a schema version and can be validated before loading.
7. The UI consumes a complete turn result rather than reconstructing truth from ambient events.
8. LLM failures must fall back to deterministic dialogue or action selection without breaking a turn.

## Decisions to Revisit After the First Full Playtest

- Whether 10-minute turns create the desired pacing.
- Whether three interview exchanges are too restrictive or too generous.
- Whether accusation support should be hard-gated or affect only the ending grade.
- Whether murderer evidence manipulation improves play or merely creates confusion.
- Whether vanilla JavaScript remains comfortable as the evidence board and timeline become richer.
