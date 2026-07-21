# Active Build Status

**Updated:** 2026-07-21

**Controlling direction:** [product_north_star.md](product_north_star.md)

**Design roadmap and acceptance gate:** [AI_Murder_Mystery_Game_Design_Roadmap.md](AI_Murder_Mystery_Game_Design_Roadmap.md)

**Settled decisions:** [decision_log.md](decision_log.md)

## Playable now

- Normal New Story now requires OpenRouter and generates one complete canonical mystery from the predefined Ashwick Manor package plus either an automatic or manual eight-person cast selected from all 24 cards.
- The first independent procedural acceptance case now compiles from a provider-shaped document, seed 731, Ashwick Manor, and an arbitrary eight-card cast without loading or remapping either authored crime spine. It passes the production API, autonomous activity, solve, debrief replay, and generated-save round trip; see [procedural_acceptance_report.md](procedural_acceptance_report.md).
- The provider-free authored-projection matrix drives four automatic ensembles covering all 24 cards plus an arbitrary manual ensemble through the real API admission boundary; each reaches turn-six events, v5 save/load without a provider, and a supported ending. Because these cases reuse an Ashwick crime spine, this is a regression fixture rather than proof of procedural-case acceptance.
- Two complete Ashwick Manor mysteries remain as explicitly labelled offline demo/test fixtures with distinct culprits, scenes, motives, and three-part proof paths.
- Twenty-four validated CCv3 characters plus bounded JSON import, safe preview, local drafts, collision-safe atomic replacement, and export through an in-game editor.
- Authoritative discovery, investigation, interview, evidence, notebook, accusation, timeout, result, and debrief loops. Timeout now produces a distinct unsolved public outcome and debrief instead of a null result.
- Deterministic ten-minute turns now fire bounded, host-authored atmosphere events exactly once at their declared turn and include them in the immutable NPC-phase snapshot. Generated games issue seven separately partitioned living-NPC planning calls; each agent sees only its own byte-bounded private briefing/state and one finite engine-authored action set.
- The murderer alone receives the canonical crime truth. Agents can select movement, holding, in-place investigation, approach-to-player behaviour, player assistance, authorized misdirection, world-event reaction, permitted evidence defense, private alibis, known observations, authorized lies, and non-factual reactions. Truthful observations transfer only their fact IDs to one co-located listener; social IDs bind the exact target and claim, and one NPC cannot participate in more than one private exchange in a phase.
- During a generated-case interview, only the target NPC receives the question, its private briefing/runtime state, and a finite engine-authored response set. It may select an alibi, known truthful observation, authorized lie, or evasion by opaque ID; truthful disclosures teach only their declared fact IDs.
- Provider responses select IDs only, fall back independently to useful deterministic authored choices, and cannot patch world state. Interview IDs are bound to the question and exchange, selected claims survive save/replay, and cancellation during optional post-commit portrayal cannot duplicate an already-recorded exchange.
- Replay-verified v5 local saves with legacy-v1/v2/v3/v4 loading, exact historical rules metadata, and deterministic scheduled-event replay. A golden v4 fixture emitted by the preserved foundation proves positional NPC histories restore exactly; new post-restore actions use current semantic rules and receive the current audit format.
- Generated final accusations evaluate culprit, method, motive, timeline, a complete selected evidence route, and confirmed contradictions. The debrief API exposes immutable canonical truth, the complete normalized NPC action trace, final player/NPC knowledge, and replay verification.
- Bounded notebooks, accusation payloads, conversation memories, and action histories, with rejected actions leaving time and history unchanged.
- Frozen builds bundle all authored content and write config, saves, and card drafts to durable per-user storage. The build fails closed and smoke-tests the real artifact across automatic casting, an exact manual cast, both fixed cases, and v5 save/load.
- The package-verification matrix builds and launches the distributable successfully on Windows, Ubuntu, and macOS; the latest three-run matrix completed without annotations.
- 379 automated unit, contract, adversarial, persistence, AI-boundary, concurrency, packaging, cast-reachability, frontend-behavior, and solve tests (363 Python plus 16 Node tests). The deterministic authored soak matrix solves every pooled card against both authored mystery spines; a separate independent provider-shaped case proves procedural variety and remains solvable after six autonomous turns. Desktop/mobile browser playthroughs cover both demo mysteries and the card editor, including exact-once scheduled-event presentation.

## Generated-story architecture now connected

- A provider-shaped scenario document can now describe complete canonical truth plus public framing. Host-owned IDs, turn policy, and opening prose are injected locally, and schema, chronology, participant co-location, reciprocal solution linkage, clue-count, red-herring, discovery-path, evidence-cycle, schedule, private-knowledge provenance, means/motive/opportunity, distinct private-state, two-independent-route, unique-culprit, interview-disclosure, and public-spoiler validation must all pass before the document is admitted. Evidence cannot both implicate and exonerate the same character, proof routes cannot exonerate the culprit, and generated murderer alibi/lie prose is kept out of player-facing candidates regardless of its manifest.
- Runtime discovery now enforces clue prerequisites and physical room/slot placement, while admission rejects unreachable prerequisite chains and action routes the engine cannot execute. Accepted generation constraints therefore remain true during play rather than existing only on paper.
- The normal New Story route requires a configured provider. Selected card/location data is sent to one canonical scenario-generation call; only a fully admitted result atomically replaces the current session.
- Accepted generated truth is embedded only in local saves with a content fingerprint, revalidated, and replay-checked during restore. Restore does not make another provider call.
- Initial implementation and automated tests feed the exact production boundary a dummy provider document and spend no OpenRouter credits.

## Milestone interpretation

The first procedural case has passed the technical acceptance criteria preserved in Appendix A of the design roadmap. That is implementation evidence, not a declaration that the product milestone or MVP is finished. Under the superseding roadmap, **Phase 1 remains active** until the blind-playtesting gate is met.

## Controlled DeepSeek V4 evaluation in progress

The general real-provider hold is lifted only for a paired, budget-capped comparison of `deepseek/deepseek-v4-pro` and `deepseek/deepseek-v4-flash` through the existing OpenRouter endpoint. Exact returned-model verification, serving-provider recording, no fallback model, parameter-compatible routing, atomic inclusive-charge accounting, and a frozen experiment manifest must pass before substantive traffic. The run stops at the human blind-playtest gate and cannot declare Phase 1 or the MVP complete.

Three revision-1 Flash preflights across 2026-07-21 and 2026-07-22 stopped with HTTP 404 before a generation ID. Comparison with tag `v2.0.0` isolated the cause: revision 1 added a direct-DeepSeek-only BYOK restriction that the working legacy integration never used. Revision 2 restores OpenRouter endpoint routing while retaining the exact model slugs, high reasoning effort, bounded parameters, no fallback model, and fail-closed accounting. Pro and all substantive generation/playtest traffic remain unrun. OpenRouter usage remains USD 0.00; the local ledger conservatively retains USD 0.00016230 across the three unresolved revision-1 reservations.

The offline execution gate is now prepared without further provider traffic: candidate-level admission diagnostics, first-admitted-in-manifest-order crossed selection, pristine generated-save restoration, concurrency-one measured NPC calls, classified runtime fallbacks, and a restricted player-only API with append-only transcript sealing. The restricted surface omits generation, demo, settings, model, card, save/load, OpenAPI, and premature debrief routes during Phase A.

## Remaining Phase 1 acceptance work and limitations

1. Commit experiment revision 2 and rerun the two tiny OpenRouter preflights. Proceed only if each response proves the exact requested model and trusted inclusive charge. Real-provider playtesting outside this controlled experiment remains on hold. The earlier procedural acceptance run used a local dummy provider and spent no OpenRouter credits.
2. The expanded gate still requires three procedural cases with different seeds and materially different casts or locations to pass automated validation.
3. Two blind sub-agent playthroughs on different cases must use only the actual player interface and reach fair, evidence-supported accusations without hidden-state access.
4. At least one human blind playthrough is required before the MVP may be described as trustworthy.
5. Ashwick Manor is still the only authored location package. The pipeline accepts an arbitrary compatible package, but multi-location content breadth has not yet been demonstrated.
6. Autonomous behaviour is intentionally turn-based and selected from finite host-authored actions. Turn-based play remains supported; continuous event-driven simulation is a possible later selectable mode.
7. The complete audit is available through the debrief API, while the browser currently presents the player-oriented solution rather than every private audit field.
8. Provider rejection rate and narrative quality across real models have not been measured. Structural rejection is fail-closed by design.

The original continuous-real-time prototype documents are preserved on the repository's [`archived` branch](https://github.com/DilanRG/ai-murder-mystery-v2/tree/archived/docs). They are intentionally absent from the active branch and do not describe the active turn-based build.
