# Active Build Status

**Updated:** 2026-07-21
**Controlling specification:** [project_brief.md](project_brief.md)

## Playable now

- Normal New Story now requires OpenRouter and generates one complete canonical mystery from the predefined Ashwick Manor package plus either an automatic or manual eight-person cast selected from all 24 cards.
- Two complete Ashwick Manor mysteries remain as explicitly labelled offline demo/test fixtures with distinct culprits, scenes, motives, and three-part proof paths.
- Twenty-four validated CCv3 characters plus bounded JSON import, safe preview, local drafts, collision-safe atomic replacement, and export through an in-game editor.
- Authoritative discovery, investigation, interview, evidence, notebook, accusation, timeout, result, and debrief loops.
- Deterministic ten-minute turns. Generated games issue seven separately partitioned living-NPC planning calls from one immutable NPC-phase snapshot; each agent sees only its own byte-bounded private briefing/state and one finite engine-authored action set.
- The murderer alone receives the canonical crime truth. Agents can select movement, holding, permitted evidence defense, private alibis, known observations, authorized lies, and non-factual reactions. Truthful observations transfer only their fact IDs to one co-located listener; social IDs bind the exact target and claim, and one NPC cannot participate twice in a phase.
- Provider responses select action IDs only, fall back independently, and cannot patch world state; bounded post-commit interview portrayal remains available.
- Replay-verified v2 local saves with legacy-v1 loading, truth-redacted APIs, responsive desktop/mobile UI, and distinct portrait placeholders.
- Bounded notebooks, accusation payloads, conversation memories, and action histories, with rejected actions leaving time and history unchanged.
- Frozen builds bundle all authored content and write config, saves, and card drafts to durable per-user storage. The build fails closed and smoke-tests the real artifact across automatic casting, an exact manual cast, both fixed cases, and v2 save/load.
- The package-verification matrix builds and launches the distributable successfully on Windows, Ubuntu, and macOS; the latest three-run matrix completed without annotations.
- 247 automated unit, contract, adversarial, persistence, AI-boundary, concurrency, packaging, cast-reachability, frontend-boundary, and solve tests (237 Python plus ten Node tests). The deterministic soak matrix solves every pooled card against both dummy mystery spines; desktop/mobile browser playthroughs cover both mysteries and the card editor.

## Generated-story architecture now connected

- A provider-shaped scenario document can now describe complete canonical truth plus public framing. Host-owned IDs and turn policy are injected locally, and schema, chronology, reciprocal solution linkage, clue-count, red-herring, discovery-path, evidence-cycle, schedule, unique-culprit, and public-spoiler validation must all pass before the document is admitted.
- Runtime discovery now enforces clue prerequisites and physical room/slot placement, while admission rejects unreachable prerequisite chains and action routes the engine cannot execute. Accepted generation constraints therefore remain true during play rather than existing only on paper.
- The normal New Story route requires a configured provider. Selected card/location data is sent to one canonical scenario-generation call; only a fully admitted result atomically replaces the current session.
- Accepted generated truth is embedded only in local saves with a content fingerprint, revalidated, and replay-checked during restore. Restore does not make another provider call.
- Initial implementation and automated tests feed the exact production boundary a dummy provider document and spend no OpenRouter credits.

## Still to build

1. Conduct the first real-provider playtest, then tune the scenario prompt, retry policy, model defaults, latency, token use, and case variety from observed failures.
2. Let the interviewed NPC's private agent choose among engine-authored truthful, incomplete, evasive, and authorized-lie claims before the separate portrayal pass; add visible bounded reactions without granting state-authoring authority.
3. Repeat desktop/mobile browser regression testing against real generated cases and harden packaging around provider configuration and failure recovery.
4. Add expression artwork after the AI-driven game loop is stable.

The original continuous-real-time prototype documents are historical references. They do not describe the active turn-based build.
