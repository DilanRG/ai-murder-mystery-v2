# Active Build Status

**Updated:** 2026-07-21
**Controlling specification:** [project_brief.md](project_brief.md)

## Playable now

- Two complete Ashwick Manor mysteries with distinct culprits, scenes, motives, and three-part proof paths.
- Stable seeded selection between complete validated crime spines, including reproducible save/load metadata and legacy v1-save compatibility.
- Eight validated CCv3 characters plus bounded JSON import, safe preview, local drafts, collision-safe atomic replacement, and export through an in-game editor.
- Authoritative discovery, investigation, interview, evidence, notebook, accusation, timeout, result, and debrief loops.
- Deterministic ten-minute turns and seven-NPC batch resolution from an immutable NPC-phase snapshot, with authored initial suspicions and bounded, fact-free private NPC exchanges outside the player's room.
- Optional provider-neutral AI portrayal and intent selection. Every remote output is schema constrained and can only reference engine-authorized facts or finite action IDs.
- Replay-verified v2 local saves with legacy-v1 loading, truth-redacted APIs, responsive desktop/mobile UI, and distinct portrait placeholders.
- Bounded notebooks, accusation payloads, conversation memories, and action histories, with rejected actions leaving time and history unchanged.
- Frozen builds bundle all authored content and write config, saves, and card drafts to durable per-user storage. The build fails closed and smoke-tests the real artifact across both cases and v2 save/load.
- 140 automated unit, contract, adversarial, persistence, AI-boundary, concurrency, packaging, and two-spine solve tests, plus desktop/mobile browser playthroughs of both mysteries and the card editor.

## Still to build

1. Run the configured macOS/Linux release jobs to confirm the Windows-verified packaged smoke test cross-platform.
2. Additional expression artwork and further deterministic emotional/social variety after the distributable MVP is stable.

The original continuous-real-time prototype documents are historical references. They do not describe the active turn-based build.
