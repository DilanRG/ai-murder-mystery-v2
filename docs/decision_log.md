# AI Murder Mystery Game — Decision Log

Short, dated records of settled product and architecture choices. This log records decisions, not implementation status or future work. The [Product North Star](product_north_star.md) defines the invariant product intent, the [Game Design Roadmap](AI_Murder_Mystery_Game_Design_Roadmap.md) owns sequencing and acceptance gates, and [Active Build Status](active_status.md) records what is currently verified.

Add a new entry when a decision is settled or superseded; do not silently rewrite an older entry. Link the replacement from the earlier entry when practical.

## 2026-07-21

- **Product identity:** The product is **AI Murder Mystery Game**. “Ashwick” is reserved for intentional in-world sample content and compatibility identifiers, not the product, application, or overall build.
- **Cast boundary:** A new game selects eight NPC Character Card V3 cards. One is the victim and seven remain alive; the player detective is separate from all eight cards.
- **Murderer role:** Exactly one of the seven living NPCs is the murderer. The other six living NPCs are innocent suspects, though they may still conceal unrelated secrets or mislead the player.
- **Authority:** The engine owns canonical truth, time, topology, evidence, perception, action resolution, and the final verdict. Models may propose bounded actions and portray dialogue, but may not author or patch world truth.
- **State separation:** Canonical truth, world state, observations, beliefs, claims, and player knowledge are distinct data layers. A statement does not become a fact merely because an NPC or model emitted it.
- **Character overlays:** Reusable character cards provide identity and personality. Case roles, private observations, beliefs, secrets, relationships, goals, and runtime memory belong to case-specific overlays.
- **Case admission:** A generated candidate becomes immutable canonical truth only after schema, chronology, provenance, knowledge, means/motive/opportunity, accessibility, and unique-culprit validation passes.
- **Solvability:** Every admitted procedural case must retain at least two independent evidentiary routes to one uniquely best-supported culprit. Bounded murderer counterplay may not eliminate the final viable route.
- **Authored fixtures:** Existing authored Ashwick cases remain playable regression fixtures. They do not count as procedural-case acceptance evidence.
- **Play modes:** Turn-based play remains supported as a first-class mode. Continuous event-driven simulation may become a later selectable mode; it does not replace the turn-based foundation.
- **Player visibility:** Player-facing interfaces receive only a perception-filtered projection. Maps, APIs, dialogue, saves, and UI state must not leak canonical truth or private NPC state during play.
- **Testing standard:** Tests must be falsifiable and adversarial. Procedural acceptance also requires blind playthroughs through the actual player interface without source, debug, save-file, or hidden-state access.
- **Phase 1 gate:** The procedural engine has passed its first technical generated-case gate. Phase 1 remains active until three materially varied procedural cases pass validation, two blind interface-only agent playthroughs reach fair supported accusations on different cases, authored regressions remain green, and at least one human blind playthrough is completed.
- **Provider testing hold:** Real-provider playtesting remains paused until the project owner lifts the hold. Dummy providers exercise the production admission boundary without spending API credits meanwhile.
- **Provider direction:** OpenRouter is the current generation adapter, not a permanent product dependency. A later provider abstraction should support major APIs and compatible local endpoints without placing provider logic in the engine.
- **Difficulty model:** Difficulty is multi-dimensional and should be expressed through named profiles composed from subsystem presets, with advanced custom controls later.
- **Location authoring:** A validated room graph is the authoritative first representation of a location package. A 2D map is a later perception-filtered view over that graph, not a second source of truth.
- **Forensics sequencing:** Forensic and DFIR systems are deferred until the core mystery game is proven and the forensic collaborator has completed a blind playtest.
- **Controlled real-provider exception:** The real-provider testing hold is lifted only for the budget-capped DeepSeek V4 Pro/Flash evaluation. The experiment has a USD 8.50 soft stop, USD 9.50 operational hard stop, and USD 0.50 accounting reserve; all other real-provider playtesting remains paused.
- **Two-phase agent acceptance:** Agent acceptance is split into Phase A blind intended play and Phase B adversarial black-box play. Phase B begins only after Phase A passes, and post-fix normal play must follow adversarial fixes.

## 2026-07-22

- **OpenRouter evaluation route:** The DeepSeek V4 comparison uses the OpenRouter endpoint and the exact `deepseek/deepseek-v4-pro` or `deepseek/deepseek-v4-flash` model slug, matching the proven legacy-v2 integration. OpenRouter may choose or fail over between compatible serving providers; no fallback model is configured or accepted. Every successful response must report the exact requested model, serving provider, accounting mode, and inclusive external charge. This supersedes the experiment-only decision to require a direct DeepSeek BYOK endpoint.
- **DeepSeek upstream clarification:** This supersedes the preceding OpenRouter-route interpretation. Requests still enter through OpenRouter, but the experiment must force the `deepseek` upstream provider, use the owner's prioritized DeepSeek BYOK key, disable shared/provider fallback, and require `is_byok=true`. The measured adapter omits `top_k` because the direct V4 endpoints do not support it; the ordinary product adapter retains its legacy default.
