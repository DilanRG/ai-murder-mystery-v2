# Active Build Status

**Updated:** 2026-07-22

**Controlling direction:** [product_north_star.md](product_north_star.md)

**Design roadmap and acceptance gate:** [AI_Murder_Mystery_Game_Design_Roadmap.md](AI_Murder_Mystery_Game_Design_Roadmap.md)

**Settled decisions:** [decision_log.md](decision_log.md)

## Playable now

- Normal New Story now requires OpenRouter and constructs one complete canonical mystery in four bounded stages from the predefined Ashwick Manor package plus either an automatic or manual eight-person cast selected from all 24 cards.
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
- 405 automated unit, contract, adversarial, persistence, AI-boundary, concurrency, packaging, cast-reachability, frontend-behavior, and solve tests (389 Python plus 16 Node tests). The deterministic authored soak matrix solves every pooled card against both authored mystery spines; a separate independent provider-shaped case proves procedural variety and remains solvable after six autonomous turns. Desktop/mobile browser playthroughs cover both demo mysteries and the card editor, including exact-once scheduled-event presentation.

## Generated-story architecture now connected

- A provider-shaped scenario document can now describe complete canonical truth plus public framing. Host-owned IDs, turn policy, and opening prose are injected locally, and schema, chronology, participant co-location, reciprocal solution linkage, clue-count, red-herring, discovery-path, evidence-cycle, schedule, private-knowledge provenance, means/motive/opportunity, distinct private-state, two-independent-route, unique-culprit, interview-disclosure, and public-spoiler validation must all pass before the document is admitted. Evidence cannot both implicate and exonerate the same character, proof routes cannot exonerate the culprit, and generated murderer alibi/lie prose is kept out of player-facing candidates regardless of its manifest.
- Runtime discovery now enforces clue prerequisites and physical room/slot placement, while admission rejects unreachable prerequisite chains and action routes the engine cannot execute. Accepted generation constraints therefore remain true during play rather than existing only on paper.
- The normal New Story route requires a configured provider. Selected card/location data is sent through crime/fact, evidence/solution, private-overlay, and public-presentation stages. Each stage has a strict schema, bounded stage-local repair, and the same byte-stable two-message prompt prefix so providers with automatic prefix caching can reuse it. Mutable repair feedback appears only after that prefix.
- Evidence-to-fact links are derived deterministically during assembly rather than independently authored in two stages. The complete truth passes the existing global chronology, provenance, knowledge, feasibility, accessibility, two-route, and unique-culprit validator before public presentation is requested; no accepted partial stage can replace the active session.
- The measured runner distinguishes one candidate pipeline from its individual stage requests and repairs. A cell may run one candidate pipeline with at most three attempts in any stage; malformed or rejected stage requests remain counted and linked to their provider records.
- Accepted generated truth is embedded only in local saves with a content fingerprint, revalidated, and replay-checked during restore. Restore does not make another provider call.
- Initial implementation and automated tests feed the exact production boundary a dummy provider document and spend no OpenRouter credits.

## Milestone interpretation

The first procedural case has passed the technical acceptance criteria preserved in Appendix A of the design roadmap. That is implementation evidence, not a declaration that the product milestone or MVP is finished. Under the superseding roadmap, **Phase 1 remains active** until the blind-playtesting gate is met.

## Controlled DeepSeek V4 evaluation in progress

The general real-provider hold is lifted only for a paired, budget-capped comparison of direct `deepseek-v4-pro` and `deepseek-v4-flash`. Exact model resolution, direct transport identity, no model fallback, complete token-meter accounting, and a frozen experiment manifest must pass before substantive traffic. The run stops at the human blind-playtest gate and cannot declare Phase 1 or the MVP complete. Normal game generation remains OpenRouter-compatible; the direct transport is isolated to the controlled evaluation.

Three revision-1 Flash preflights stopped before generation because `top_k=40` made the direct DeepSeek endpoint ineligible under `require_parameters=true`. A revision-2 WandB diagnostic cost USD 0.00000490 but was invalidated. Revision 3 exposed OpenRouter's privacy/guardrail-policy block. Revision 4 verified both direct models, then found Pro spent the entire 16,384-token allowance on reasoning and emitted no JSON. Revision 5 corrected the 32,768-token transport seam, but P1/Flash still failed all three one-shot admission attempts: two structurally inconsistent full documents and one truncated JSON document. That cell cost USD 0.02518964 and is preserved in the ignored private baseline archive. Revision 6 replaced the one-shot contract with the staged cache-aware pipeline. Its exact Flash and Pro preflights passed. The first P1/Flash core stage then returned successfully, but the local command controller timed out after the next request had been reserved. P1 is retained as an operationally invalidated cell, not a model-quality failure, and will not be silently retried.

Revision 7 activates the predeclared R1 reserve as the balanced replacement for P1 and freezes the executable matrix to exactly P2, P3, and R1. The execution plan, manifest digest, replacement provenance, current cell, pre-transport request intents, provider-response events, stage-attempt outcomes, and completed cells are fsync-persisted before or immediately after their corresponding boundary. Any interrupted or incomplete plan—or a revision-7 generation intent whose plan is missing—refuses automatic restart so a controller failure cannot create a hidden duplicate request. Crossed selection accepts R1 only when both model cells carry the frozen P1-replacement provenance. The owner has explicitly authorized sending the disclosed cards, location, schema, prompts, and accepted-stage material to the external DeepSeek API for this capped evaluation.

The provider dashboard showed USD 0.19 for the AI-MMG key over the preceding seven days (33 requests, 610,928 tokens) when reconciled on 2026-07-22. That is the authoritative observed billed usage. The local journal's unresolved reservations are deliberately pessimistic worst-case exposure holds, not spend, and remain separately visible for fail-closed budget enforcement.

The offline execution gate is now prepared without further provider traffic: durable request/stage diagnostics, exact-plan crossed selection, pristine generated-save restoration, concurrency-one measured NPC calls, classified runtime fallbacks, and a restricted player-only API with append-only transcript sealing. The restricted surface omits generation, demo, settings, model, card, save/load, OpenAPI, and premature debrief routes during Phase A. Revision-7 controls pass the full 389-test backend suite, all 16 frontend tests, and the Vite production build; exact-commit paid preflights remain pending.

## Remaining Phase 1 acceptance work and limitations

1. Commit and push revision 7, re-record its two tiny exact-commit preflights, then execute the durable P2/P3/R1 staged matrix. Proceed only while exact direct model, transport `deepseek_direct`, no fallback, complete token-meter accounting, staged per-role wire limits, and the budget gate remain verified. Real-provider playtesting outside this controlled experiment remains on hold.
2. The expanded gate still requires three procedural cases with different seeds and materially different casts or locations to pass automated validation.
3. Two blind sub-agent playthroughs on different cases must use only the actual player interface and reach fair, evidence-supported accusations without hidden-state access.
4. At least one human blind playthrough is required before the MVP may be described as trustworthy.
5. Ashwick Manor is still the only authored location package. The pipeline accepts an arbitrary compatible package, but multi-location content breadth has not yet been demonstrated.
6. Autonomous behaviour is intentionally turn-based and selected from finite host-authored actions. Turn-based play remains supported; continuous event-driven simulation is a possible later selectable mode.
7. The complete audit is available through the debrief API, while the browser currently presents the player-oriented solution rather than every private audit field.
8. Provider rejection rate and narrative quality across real models have not been measured. Structural rejection is fail-closed by design.

The original continuous-real-time prototype documents are preserved on the repository's [`archived` branch](https://github.com/DilanRG/ai-murder-mystery-v2/tree/archived/docs). They are intentionally absent from the active branch and do not describe the active turn-based build.
