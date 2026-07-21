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
