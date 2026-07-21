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
- During a generated-case interview, only the target NPC receives the question, its private briefing/runtime state, and a finite engine-authored response set. It may select an alibi, known truthful observation, authorized lie, or evasion by opaque ID; truthful disclosures teach only their declared fact IDs.
- Provider responses select IDs only, fall back independently to useful deterministic authored choices, and cannot patch world state. Interview IDs are bound to the question and exchange, selected claims survive save/replay, and cancellation during optional post-commit portrayal cannot duplicate an already-recorded exchange.
- Replay-verified v3 local saves with legacy-v1 loading and exact per-action replay of the historical prefix in pre-interview-agent v2 saves; every new post-restore exchange immediately uses hardened rules. Truth-redacted APIs, responsive desktop/mobile UI, and distinct portrait placeholders remain in place.
- Bounded notebooks, accusation payloads, conversation memories, and action histories, with rejected actions leaving time and history unchanged.
- Frozen builds bundle all authored content and write config, saves, and card drafts to durable per-user storage. The build fails closed and smoke-tests the real artifact across automatic casting, an exact manual cast, both fixed cases, and v3 save/load.
- The package-verification matrix builds and launches the distributable successfully on Windows, Ubuntu, and macOS; the latest three-run matrix completed without annotations.
- 276 automated unit, contract, adversarial, persistence, AI-boundary, concurrency, packaging, cast-reachability, frontend-boundary, and solve tests (266 Python plus ten Node tests). The deterministic soak matrix solves every pooled card against both dummy mystery spines; desktop/mobile browser playthroughs cover both mysteries and the card editor.

## Generated-story architecture now connected

- A provider-shaped scenario document can now describe complete canonical truth plus public framing. Host-owned IDs and turn policy are injected locally, and schema, chronology, reciprocal solution linkage, clue-count, red-herring, discovery-path, evidence-cycle, schedule, unique-culprit, interview-disclosure, and public-spoiler validation must all pass before the document is admitted. Alibis/lies must explicitly declare disclosures and cannot expose hidden facts or directly confess; generated murderer alibi/lie prose is additionally kept out of player-facing candidates regardless of its manifest.
- Runtime discovery now enforces clue prerequisites and physical room/slot placement, while admission rejects unreachable prerequisite chains and action routes the engine cannot execute. Accepted generation constraints therefore remain true during play rather than existing only on paper.
- The normal New Story route requires a configured provider. Selected card/location data is sent to one canonical scenario-generation call; only a fully admitted result atomically replaces the current session.
- Accepted generated truth is embedded only in local saves with a content fingerprint, revalidated, and replay-checked during restore. Restore does not make another provider call.
- Initial implementation and automated tests feed the exact production boundary a dummy provider document and spend no OpenRouter credits.

## Still to build

1. Continue recursive provider-free playtesting with dummy-generated cases, varied casts, malformed inputs, state-machine extremes, and full solve paths; improve weak gameplay revealed by those runs.
2. Add visible bounded emotional reactions and richer contextual question affordances without granting agents state-authoring authority.
3. Conduct the first real-provider playtest, then tune the scenario prompt, retry policy, model defaults, latency, token use, and case variety from observed failures. This stage is explicitly on hold at the user's request and no OpenRouter credits should be spent meanwhile.
4. After that hold is lifted, repeat desktop/mobile browser regression testing against real generated cases and harden provider configuration/failure recovery from observed behavior.
5. Add expression artwork after the AI-driven game loop is stable.

The original continuous-real-time prototype documents are historical references. They do not describe the active turn-based build.
