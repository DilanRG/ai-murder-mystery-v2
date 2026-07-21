# Active Build Status

**Updated:** 2026-07-21
**Controlling specification:** [project_brief.md](project_brief.md)

## Playable now

- Two complete Ashwick Manor mysteries with distinct culprits, scenes, motives, and three-part proof paths.
- Stable seeded selection between complete validated crime spines plus automatic or manual eight-person casting from 24 cards, including reproducible save/load metadata and legacy v1-save compatibility.
- Twenty-four validated CCv3 characters plus bounded JSON import, safe preview, local drafts, collision-safe atomic replacement, and export through an in-game editor.
- Authoritative discovery, investigation, interview, evidence, notebook, accusation, timeout, result, and debrief loops.
- Deterministic ten-minute turns and seven-NPC batch resolution from an immutable NPC-phase snapshot, with authored initial suspicions and bounded, fact-free private NPC exchanges outside the player's room.
- Optional provider-neutral AI story direction, portrayal, and intent selection. The director generates bounded public presentation only; every remote output is schema constrained and cannot alter case truth.
- Replay-verified v2 local saves with legacy-v1 loading, truth-redacted APIs, responsive desktop/mobile UI, and distinct portrait placeholders.
- Bounded notebooks, accusation payloads, conversation memories, and action histories, with rejected actions leaving time and history unchanged.
- Frozen builds bundle all authored content and write config, saves, and card drafts to durable per-user storage. The build fails closed and smoke-tests the real artifact across automatic casting, an exact manual cast, both fixed cases, and v2 save/load.
- The package-verification matrix builds and launches the distributable successfully on Windows, Ubuntu, and macOS; the latest three-run matrix completed without annotations.
- 212 automated unit, contract, adversarial, persistence, AI-boundary, concurrency, packaging, cast-reachability, frontend-boundary, and solve tests (206 Python plus six Node tests). The deterministic soak matrix solves every pooled card against both dummy mystery spines; desktop/mobile browser playthroughs cover both mysteries and the card editor.

## Architecture correction in progress

- A provider-shaped scenario document can now describe complete canonical truth plus public framing. Host-owned IDs and turn policy are injected locally, and schema, chronology, reciprocal solution linkage, clue-count, red-herring, discovery-path, evidence-cycle, schedule, unique-culprit, and public-spoiler validation must all pass before the document is admitted.
- Runtime discovery now enforces clue prerequisites and physical room/slot placement, while admission rejects unreachable prerequisite chains and action routes the engine cannot execute. Accepted generation constraints therefore remain true during play rather than existing only on paper.
- Initial tests feed the admission layer an authored dummy document and make no OpenRouter requests. This boundary is not yet connected to the normal New Story route.

## Still to build

1. Make validated OpenRouter scenario generation the normal New Story path; retain authored mysteries only as explicitly labelled offline/test fixtures.
2. Spawn seven separately partitioned NPC agent contexts from the accepted case and run their constrained reasoning during turn resolution.
3. Add generated-case persistence and conduct real-provider playtesting once the generation path is complete.
4. Additional expression artwork after the AI-driven game loop is stable.

The original continuous-real-time prototype documents are historical references. They do not describe the active turn-based build.
