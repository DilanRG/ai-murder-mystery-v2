---
title: "AI Murder Mystery Game"
subtitle: "Product Vision, Systems Design, and Development Roadmap"
date: "Working Design Brief - 21 July 2026"
---

# Document purpose

This document consolidates the current product vision, design decisions, architecture, active Codex milestone, testing strategy, player-facing systems, content framework, provider strategy, user interface direction, and longer-term forensic ambitions discussed during project planning.

It is a living design brief, not a frozen implementation contract. It deliberately separates what is **committed now**, what is **planned next**, what is **deferred**, and what remains **open for design**.

The product name is **AI Murder Mystery Game**. "Ashwick" is not the product name. It may remain only where it is intentionally used as the in-world name of an existing sample location, case, or regression fixture.

# Decision summary

| Area | Current decision | Status |
|---|---|---|
| Product identity | The product is named **AI Murder Mystery Game**. Existing authored content is sample content, not the identity of the product. | Committed |
| Core cast | A new game selects eight NPC Character Card V3 cards. One becomes the victim, seven remain alive, and one of those seven is the murderer. The player detective is separate from the eight selected cards. | Committed |
| Core fantasy | A fixed, logically coherent murder exists inside a dynamic social world populated by autonomous NPC agents. | Committed |
| Authority | The game engine owns canonical truth, time, locations, evidence, perception, and action resolution. Models may propose actions and dialogue but may not rewrite reality. | Committed |
| Current milestone | Generate and validate a new solvable case from a compatible location, cast, and seed, then run it with seven autonomous NPCs. | Active |
| Existing authored cases | Preserve them as playable regression fixtures. They do not satisfy the procedural acceptance criterion. | Committed |
| Play mode | Keep the current turn-based mode. It is useful in its own right and supports batching, reproducible testing, and cheaper agent orchestration. | Committed |
| Continuous simulation | A possible later selectable mode, not part of the active milestone. | Deferred |
| Player-as-murderer mode | A later expansion, not part of the active milestone. | Deferred |
| Testing | Tests must be falsifiable and adversarial. Passing self-authored tests is not enough; generated cases must also survive blind playtesting through the player interface. | Committed |
| Difficulty and settings | Difficulty is multi-dimensional. A top-level profile selects presets from several subsystem families; custom profiles may expose the underlying parameters. | Planned next |
| Providers | Build a broad provider abstraction covering major API providers and generic local OpenAI-compatible endpoints. Provider flexibility is a release feature, not merely a current cost workaround. | Planned |
| Interface | A three-pane interface centered on an interactive 2D map, live scene and dialogue view, actions, contextual inspection, and a notebook/evidence pane. | Planned |
| User content | Import, normalize, edit, and export Character Card V1/V2/V3 content; support user-authored location packs and maps. | Planned |
| Forensics | Add the forensic simulation only after the core game is proven and after the forensic collaborator has blind-playtested the MVP. | Deferred, architecturally anticipated |

# 1. Product origin and vision

The original inspiration came from a well-made closed-room murder scenario shown in a Minecraft modpack video, itself drawing on the atmosphere of *Murder on the Orient Express*. The first concept was not an agent simulation. It was closer to a custom character-card framework for dynamic tavern-style group conversations.

As agentic AI systems became more capable, the concept evolved into something more distinctive: the non-player characters would not merely generate dialogue. They would become persistent agents living inside an authoritative simulated world.

The intended product is therefore not just a murder mystery with AI-written prose. It is a **procedural closed-circle murder simulation** in which:

- the murder has a fixed, validated truth;
- each NPC knows only a private subset of that truth;
- NPCs hold beliefs that may be incomplete or wrong;
- characters have secrets, loyalties, motives, fears, and personal goals;
- NPCs move, converse, investigate, conceal, disclose, assist, misdirect, and react;
- the player explores the location, observes the evolving social situation, gathers evidence, constructs a theory, and makes an evidence-supported accusation.

The defining tension is **fixed truth versus dynamic behavior**. The crime must remain fair and solvable even though the people inside the world are not following a single fixed script.

## 1.1 Product pillars

1. **A real mystery, not improvised truth.** The culprit, method, motive, timeline, evidence, and knowledge boundaries exist before play and cannot be casually rewritten by a model.
2. **Autonomous social actors.** NPCs are not dialogue skins. They maintain private state, form plans, make choices, remember interactions, and pursue goals.
3. **Player-led investigation.** The player moves, observes, interviews, searches, records, compares, hypothesizes, and accuses.
4. **Procedural replayability with validation.** Different casts, locations, and seeds can generate different cases, but generation is constrained by solvability and fairness checks.
5. **A reusable framework.** Character cards, location packs, provider adapters, profiles, and creator tools make the system extensible rather than a one-case game.
6. **A future forensic training layer.** The same canonical event graph can eventually generate realistic physical and digital artifacts for investigation and education.

# 2. Canonical scenario and player loop

## 2.1 Game setup

A new game begins with:

- one validated location package;
- eight compatible Character Card V3 cards;
- one deterministic seed;
- a selected game profile and runtime configuration.

The player may manually select the location and eight cards, or allow the engine to choose compatible content from the available pools.

The case compiler assigns:

- one selected NPC as the victim;
- one of the seven living NPCs as the murderer;
- six other living NPCs with their own secrets, motives, relationships, observations, and possible reasons to lie;
- the player as a separate detective character.

"Not the murderer" does not mean "innocent in every respect." An NPC may be protecting an affair, a theft, a professional failure, a family secret, another character, or an unrelated crime. Someone may have a reason to help the detective. Someone else may have a reason to protect or assist the murderer without being the killer. Red herrings should usually emerge from real secondary secrets rather than arbitrary false clues.

## 2.2 Case compilation

The case-generation model may propose a structured candidate, but prose alone does not become reality. The candidate is converted into or produced as schema-constrained data containing at least:

- culprit, victim, motive, method, and opportunity;
- exact canonical event timeline;
- character schedules and opportunity windows;
- location and object interactions;
- physical evidence and evidence provenance;
- witness observations and hearing conditions;
- private secrets and unrelated suspicious behavior;
- relationship assignments and loyalties;
- cover stories, lies, and mistaken beliefs;
- red-herring explanations;
- clue-access paths;
- at least two independent evidentiary routes to the culprit.

The case validator either accepts, repairs, or rejects the candidate. Only an accepted case is compiled into immutable canonical truth.

## 2.3 Runtime initialization

Each living NPC receives only a private overlay appropriate to that character. The overlay may include:

- directly observed facts;
- information heard from others;
- inferences and suspicions;
- false beliefs;
- personal secrets;
- relationships and loyalties;
- emotional state;
- short-term and long-term goals;
- disclosure and deception policies;
- claims already made;
- known evidence;
- current plan and runtime memory.

The murderer knows the relevant facts of the crime but remains subject to the same world rules as everyone else. The murderer may attempt bounded counterplay, but may not invent evidence, teleport, erase authoritative history, or perform impossible actions.

## 2.4 Investigation loop

During play, the player should be able to:

1. Move through the location.
2. Observe rooms, people, objects, and events.
3. Inspect scenes and evidence.
4. Interview NPCs individually or in groups.
5. Overhear conversations when physically able to hear them.
6. Compare claims with observations and evidence.
7. Record clues, contradictions, timelines, and hypotheses.
8. Revisit people and locations as the social situation changes.
9. Select a suspect and assemble an accusation.

NPCs may perform many of the same world actions as the player. They are not required to become substitute detectives; their actions should follow their own motives. They may approach the player, volunteer information, conceal information, spread suspicion, confront one another, search, avoid certain people, recover an object, or investigate for self-protective reasons.

## 2.5 Accusation and resolution

The accused NPC must not be the authority that decides whether the player is right. The player submits a structured theory containing some or all of:

- culprit;
- motive;
- method or weapon;
- opportunity window;
- reconstructed sequence of events;
- contradictions or broken alibis;
- selected supporting evidence.

The authoritative engine compares that theory with the canonical case graph. This enables more nuanced outcomes than a simple name check:

- correct culprit with a weak case;
- correct culprit with an incorrect reconstruction;
- wrong culprit supported by a plausible but misleading theory;
- substantially correct case with missing details;
- complete, strongly supported solution.

Only after the engine has judged the theory should the presentation model portray denial, confession, panic, anger, escape, or refusal. Dramatic response is presentation; the verdict is game logic.

# 3. Non-negotiable design invariants

## 3.1 The engine owns reality

The game engine is authoritative for:

- canonical case truth;
- time and turn order;
- room topology and movement;
- object ownership and location;
- visibility and hearing;
- evidence provenance;
- action validity and consequences;
- knowledge propagation;
- accusation evaluation;
- save, replay, and audit state.

Models may propose actions, dialogue, plans, descriptions, and interpretations behind controlled interfaces. They may never directly edit canonical truth.

## 3.2 Truth, observation, belief, claim, and player knowledge are different data

The system must not collapse these concepts:

| Data layer | Meaning |
|---|---|
| Canonical truth | What actually happened and what currently exists in the authoritative world. |
| World state | Current positions, object state, time, active effects, and resolved consequences. |
| Observation | What a particular character directly perceived under visibility and hearing rules. |
| Belief | What that character currently thinks is true, which may be incomplete or wrong. |
| Claim | What a character says, which may be truthful, mistaken, misleading, or deliberately false. |
| Player knowledge | What the player has legitimately observed, heard, recorded, or inferred. |

This separation is essential for mystery fairness, deception, replay, and later forensic simulation.

## 3.3 The user interface receives a perception snapshot

The map, scene text, visible NPCs, dialogue, clue markers, and notebook should be generated from the player's perception and discovered knowledge, not from canonical truth. This prevents accidental spoilers and gives the game a reliable basis for stealth, overhearing, hidden movement, and uncertain information.

## 3.4 Evidence has provenance

Every clue should have a causal origin. The system should know:

- which event created it;
- who could have interacted with it;
- where and when it existed;
- who could discover it;
- whether it was moved, hidden, contaminated, or altered;
- what conclusions it supports and what it does not prove.

## 3.5 Solvability is validated, not assumed

A generated case must not be accepted merely because the model calls it solvable. Validation should check timeline consistency, means, motive, opportunity, clue accessibility, knowledge boundaries, evidence independence, and whether the culprit is uniquely best supported.

## 3.6 Existing authored content is preserved

The current authored cases remain playable regression fixtures. They are valuable foundations and test cases, but they are not the final product and do not satisfy the procedural milestone by themselves.

# 4. Proposed system architecture

| Layer | Responsibility |
|---|---|
| Character and location content | Character Card data, location graph, rooms, exits, visibility, acoustics, objects, art, and authoring metadata. |
| Case compiler | Builds a candidate murder timeline, roles, evidence, observations, secrets, relationships, alibis, and red herrings from the selected content and seed. |
| Case validator | Rejects or repairs impossible, unfair, underdetermined, inaccessible, or internally inconsistent cases. |
| Canonical case graph | Immutable murder truth, causal events, evidence provenance, and initial knowledge assignments. |
| World engine | Resolves time, movement, perception, objects, interactions, conversations, and validated action consequences. |
| NPC agent runtime | Maintains private state and asks models for bounded plans, actions, and dialogue when a decision is needed. |
| Story director | Improves pacing and visibility of interesting situations without creating facts or changing the culprit. |
| Presentation layer | Produces character voice, scene prose, emotional expression, portraits, sprites, and voice output from approved state. |
| Accusation evaluator | Compares the player's structured theory and selected evidence with the canonical graph. |
| Replay and audit system | Reconstructs authoritative state and produces post-game truth, action, knowledge, and claim histories. |
| Future forensic compiler | Derives physical and digital artifacts from the same canonical event graph. |

## 4.1 Controlled NPC action interface

NPC models should choose among engine-defined action types rather than writing arbitrary state transitions. Candidate actions include:

- move;
- approach character;
- start conversation;
- exchange information;
- volunteer information;
- challenge a claim;
- spread suspicion;
- investigate room or object;
- observe a scene;
- follow or avoid a character;
- retrieve or hide an owned or reachable item;
- seek the player;
- request help;
- revise a plan.

The engine validates preconditions, applies consequences, records observations, and wakes affected agents when necessary.

## 4.2 Turn-based execution now, event-driven execution later

The current turn-based mode should remain supported. It provides:

- deterministic and comprehensible state transitions;
- easier debugging and replay;
- natural batching of multiple NPC decisions;
- controllable cost and latency;
- a viable game mode for players who prefer deliberate investigation.

A future continuous mode should be event-driven rather than calling every model constantly. An NPC can create a high-level plan, sleep while routine movement is resolved by the engine, and wake only when the plan fails, a person approaches, new evidence appears, or an important event occurs.

# 5. Active Codex milestone

## 5.1 Goal title

**Build the Procedural Autonomous-NPC Vertical Slice for AI Murder Mystery Game**

## 5.2 Intended outcome

Starting from one validated location package, eight compatible Character Card V3 cards, and a deterministic seed, the game must generate and validate a new closed-circle murder, compile it into immutable canonical truth, assign one selected NPC as the victim, and initialize the seven living NPCs as autonomous agents. The player detective remains separate from the selected cards.

The milestone must demonstrate meaningful NPC autonomy, preserved knowledge boundaries, engine-authoritative action resolution, a fair evidence-supported accusation, deterministic replay, and a complete post-game audit.

## 5.3 Acceptance criteria

The active milestone is complete only when all of the following are demonstrated:

1. At least one case is generated from a compatible cast and location rather than loading either existing authored crime spine.
2. The generated case passes validation for timeline consistency, evidence provenance, character knowledge boundaries, means, motive, opportunity, clue accessibility, and a uniquely best-supported culprit.
3. The generated case remains solvable after autonomous NPC activity.
4. The case exposes at least two independent evidentiary routes to the culprit.
5. Each living NPC has genuinely distinct private knowledge, beliefs, secrets, relationships, goals, and runtime memory.
6. NPCs can autonomously move, converse, exchange information, investigate, approach the player, assist, misdirect, conceal, disclose, and react within engine rules.
7. Deterministic seeded replay reproduces the authoritative case and resolved action history.
8. A complete post-game truth, action, claim, and knowledge audit is available.
9. The final accusation evaluates culprit, motive, method, timeline, contradictions, and selected evidence.
10. The relevant automated suite, production build, and end-to-end generated-case acceptance scenario pass.
11. The existing authored cases remain playable and their regression tests continue to pass.

## 5.4 Required completion evidence

Before Codex declares the goal complete, it should produce an acceptance report containing:

- the exact seed;
- selected location and character cards;
- the generated case's validation results;
- the two independent evidence routes;
- a trace of autonomous NPC activity;
- the final accusation and its evaluation;
- replay and audit results;
- exact tests and commands run;
- known limitations and anything still unverified.

## 5.5 Scope control

The current run should not broaden into unrelated game modes, large visual redesigns, general polish, or the forensic simulation. The objective is to prove procedural solvability and autonomous NPC behavior on top of the preserved foundation.

# 6. Codex execution and playtesting protocol

Codex is the developer, not the sole judge of completion. The largest risks are not basic code generation. They are shallow validation, self-confirming tests, cases that are technically consistent but not discoverable by a player, and premature declarations of completion.

## 6.1 Falsifiable testing

A new regression test is strongest when it can be shown to fail against the pre-fix behavior, a deliberately mutated implementation, or a known invalid fixture. A test that passes immediately can still be useful, but a first-run pass alone is weak evidence that it protects the intended boundary.

Recommended test layers include:

- schema validation tests;
- property and invariant tests;
- deliberately invalid case fixtures;
- adversarial knowledge-leak tests;
- evidence-provenance tests;
- case solvability and uniqueness tests;
- deterministic seed and replay tests;
- NPC action permission tests;
- end-to-end accusation tests;
- packaged application smoke tests.

## 6.2 Blind sub-agent playtesting

After the build is stable, the main Codex agent should spawn a cheaper sub-agent whose role is only to play the game as a player.

The playtester should:

- use the actual player-facing application or interface;
- have no access to source code, canonical truth, private NPC state, debug endpoints, or solution files;
- record every clue discovered;
- record its evolving hypotheses and confidence;
- note confusing interfaces, dead ends, unfair inferences, or missing feedback;
- submit an accusation based only on player-visible evidence;
- return a transcript and post-play report.

The main agent may then fix reproducible MVP defects and run another blind playtest. This loop should stop at a defined acceptance gate rather than continue as endless polishing.

## 6.3 Recommended initial playtest gate

The exact numbers remain adjustable, but a sensible initial gate is:

- three procedurally generated cases with different seeds and materially different casts or locations pass automated validation;
- at least two blind sub-agent playthroughs on different cases reach a fair, evidence-supported accusation without hidden-state access;
- the authored regression fixtures remain green;
- at least one human blind playthrough is completed before calling the MVP trustworthy.

A wrong accusation does not automatically mean a failed playtest. The relevant question is whether the case was fair, the evidence was accessible, the reasoning path was understandable, and the player could explain why they were wrong.

# 7. The next phase: make it feel like a game

After the procedural autonomous-NPC milestone is stable, the next major phase is not immediately the forensic simulator. It is the game layer: settings, difficulty, presentation, onboarding, profiles, player experience, and creator-facing controls.

## 7.1 Difficulty is multi-dimensional

A single Easy-to-Hard slider is not expressive enough. Clue quantity and clue salience are independent, for example:

| Clue quantity | Loud or obvious clues | Subtle clues |
|---|---|---|
| Many | Information-rich and accessible; lower deduction burden. | Dense evidence requiring careful interpretation. |
| Few | Sparse but clear decisive evidence. | Sparse, subtle, high-risk challenge. |

The same principle applies to deception, hints, accusation strictness, case length, time pressure, NPC initiative, and red-herring density.

## 7.2 Profile and preset model

A **top-level play profile** is a named bundle that selects one preset from several preset families. A **custom profile** exposes the underlying parameters and may override any preset.

This produces three levels:

1. **Parameters** - individual knobs such as clue count, clue salience, or NPC initiative.
2. **Subsystem presets** - coherent bundles for one area, such as a clue preset or NPC preset.
3. **Top-level profiles** - complete play experiences assembled from one preset in each family.

Curated profiles should remain validated and fair. Custom profiles may allow extreme or contradictory combinations. The interface should warn that heavily customized cases may be unbalanced or unsolvable rather than pretending every configuration has a guarantee.

## 7.3 Proposed preset families

| Preset family | Example parameters |
|---|---|
| Mystery structure | Case length, number of key events, alibi complexity, relationship complexity, number of secondary secrets. |
| Clues | Quantity, salience, redundancy, distribution, recoverability, dependency on interviews versus physical search. |
| Red herrings | Count, plausibility, duration, overlap with real secrets, likelihood of implicating the wrong suspect. |
| NPC behavior | Autonomy, initiative, sociability, deception, willingness to help, memory strictness, emotional volatility, murderer counterplay. |
| Simulation | Turn duration, simultaneous decisions, batching, time pressure, event frequency, future real-time mode selection. |
| Assistance | Hint strength, automatic note capture, recap quality, contradiction highlighting, suggested next actions. |
| Accusation | Required theory fields, evidence threshold, partial credit, retry policy, strictness of timeline reconstruction. |
| AI runtime | Provider, model, context budget, reasoning effort, maximum cost, concurrency, batching, fallback behavior. |
| Presentation | Dialogue verbosity, voice, subtitles, portrait and sprite behavior, accessibility options. |

Possible curated profile names might eventually include Story, Classic Detective, Hardboiled, Social Simulation, and Forensic, but the names and exact bundles are open design work.

# 8. Provider, model, and runtime architecture

Provider support should be designed as a broad abstraction for eventual users, not as a one-off attempt to reduce current playtest cost.

## 8.1 Provider coverage

The architecture should support adapters for major API styles, including:

- OpenAI and OpenAI-compatible APIs;
- Anthropic;
- Google;
- DeepSeek;
- OpenRouter;
- generic local OpenAI-compatible endpoints.

A generic local adapter should cover systems such as KoboldCpp, LM Studio, llama.cpp server, vLLM, and similar hosts where their compatibility permits it. Provider-specific capabilities can be detected and exposed without leaking provider logic into the game engine.

## 8.2 Independent model routing

Different jobs may use different models. The framework should eventually allow separate configuration for:

- case generation;
- case repair or validation assistance;
- story direction;
- NPC planning;
- NPC dialogue;
- narration;
- blind playtesting;
- future DFIR assistance.

Individual NPCs may also be independently configurable, although sensible defaults should prevent ordinary players from facing a wall of model menus.

## 8.3 Runtime settings

Relevant runtime controls include:

- model and endpoint;
- context length or context budget;
- reasoning effort, where supported;
- output-token and cost budgets;
- timeout and retry policy;
- concurrency;
- batching;
- caching;
- fallback provider or model;
- privacy and logging behavior;
- sampler settings only where the provider and task meaningfully support them.

Turn-based mode is especially compatible with batching multiple NPC decisions in one cycle. Future continuous execution should still batch compatible events and use wake-on-event scheduling rather than constant polling.

## 8.4 Cost assumptions

Do not assume local inference is automatically cheaper. For bursty game workloads, a direct API may cost less than hardware power and idle overhead. Provider abstraction should preserve choice; actual deployment economics can be measured separately. There is no reason to embed an LLM benchmark suite inside the game.

## 8.5 Voice

ElevenLabs is a possible initial voice provider, but voice should ultimately sit behind its own adapter. Character cards or game overlays may reference a voice profile. Voice must remain optional and should not block text-only play.

# 9. Player interface and presentation

## 9.1 Three-pane layout

The current interface direction is a three-pane desktop layout.

| Region | Intended role |
|---|---|
| Left pane | Context inspector for the currently selected room, person, object, exit, or map element. Exact contents remain open. |
| Center, upper | Interactive 2D top-down map of the selected location. |
| Center, lower | Current scene, dialogue, event narration, visible or audible activity, structured actions, and optional free-form player input. |
| Right pane | Notebook, discovered clues, evidence, player timeline, contradictions, hypotheses, and later a DFIR tab or launch point. |

On smaller screens, these panes can collapse into tabs or drawers while retaining the same information architecture.

## 9.2 Interactive 2D map

Each location pack should provide a map or layout derived from the authoritative room graph. The map may show:

- player position;
- currently visible NPCs;
- discovered exits and rooms;
- selected objects;
- discovered clue markers;
- last-known NPC positions where appropriate;
- sound or event indicators that the player could legitimately perceive.

The map is a view of engine state filtered through player perception. It must never reveal hidden occupants, undiscovered passages, secret items, or canonical information the player has not earned.

## 9.3 Scene and dialogue view

The center-lower panel should present what is happening now:

- room-entry descriptions;
- nearby NPC behavior;
- conversations involving the player;
- overheard conversations;
- important movements and events;
- action choices;
- a free-form input option for actions not covered by shortcuts.

Free-form input should be parsed into an action proposal and then validated by the engine. It should not become an unrestricted way for the player or a model to rewrite the world.

## 9.4 Hearing and perception

A simple first acoustic model can use room graph distance and speech level:

- whispers are audible only at close range or under special conditions;
- normal speech is audible within the same room;
- shouting may propagate into adjacent rooms;
- doors, walls, distance, and ambient noise can later modify propagation.

The same perception system should determine which descriptions and dialogue appear in the interface.

## 9.5 Character art and emotional presentation

A character may have an optional art pack containing:

- primary portrait;
- emotion or pose sprites;
- optional full-body or scene art;
- voice profile;
- display metadata.

Dialogue can be presented in a light visual-novel style over or beneath the map. Sprites should represent outward behavior, not hidden truth. The murderer must not automatically receive a visibly guilty expression.

# 10. Character cards, locations, and user-created content

## 10.1 Character Card support

The project should support import of Character Card V1, V2, and V3, then normalize imported content into an internal V3-compatible superset with the game's extension data.

The workflow should include:

- import;
- validation;
- migration and normalization;
- editing of game-relevant fields;
- export as V3-compatible content;
- portrait extraction from PNG-based cards where available.

Case-specific information must not be permanently written into a reusable character card. Victim status, murderer status, observations, secrets, relationships, and goals belong in a per-case overlay.

## 10.2 Character editor

The editor may eventually expose:

- identity and descriptive fields;
- personality and speech style;
- goals and values;
- relationship tendencies;
- capabilities and limitations;
- compatibility tags;
- secrets that may be eligible for case use;
- portrait, sprites, and voice references;
- game-specific extension fields.

Imported card text should be treated as untrusted content data, not as executable instructions to the model or engine.

## 10.3 Location packs

A location pack should contain at least:

- rooms and sub-areas;
- exits and traversal rules;
- visibility relationships;
- hearing adjacency and sound modifiers;
- object and container definitions;
- possible evidence sites;
- interaction affordances;
- room descriptions;
- 2D layout or map coordinates;
- optional art and audio;
- compatibility and version metadata.

The creator workflow should be **room graph first, 2D layout second**. Logical topology and perception rules matter more than artwork, and the visual map should be generated from or validated against that graph.

## 10.4 User-authored scenarios

The framework could technically support fictionalized reconstructions or authorized training cases. Public official content should avoid careless use of identifiable real people, copyrighted assets, private data, or active real-world accusations. Private, redacted, or authorized packs may have different requirements.

## 10.5 Versioning and safety of custom content

User-created content introduces engineering requirements that should be planned early even if the full creator tools come later:

- schema versioning and migrations;
- save compatibility;
- clear validation errors;
- prompt-injection resistance;
- asset-rights warnings;
- missing-asset fallbacks;
- content-pack dependency tracking;
- deterministic identifiers;
- graceful failure rather than silent corruption.

# 11. Forensic and DFIR direction

The forensic layer is a major future differentiator, but it should not be built before the core mystery and agent simulation have survived playtesting.

The intended collaboration sequence is:

1. Complete the procedural autonomous-NPC MVP.
2. Have the forensic collaborator blind-playtest it as a game.
3. Gather input on difficulty, settings, evidence handling, realism, and workflow.
4. Co-design how forensic investigation integrates with the existing event, evidence, and accusation systems.
5. Build the forensic layer from the canonical event graph rather than bolting unrelated puzzles onto the interface.

## 11.1 Forensic artifacts from canonical events

The canonical timeline can eventually compile synthetic artifacts such as:

- door access and key-card logs;
- phone messages and extraction databases;
- call records and location history;
- CCTV images, clips, and metadata;
- login, filesystem, and browser artifacts;
- cloud and authentication logs;
- vehicle or smart-device telemetry;
- deleted files and partial recovery;
- network captures;
- clock drift and timezone discrepancies;
- anti-forensic actions;
- chain-of-custody records.

These artifacts must derive from the same source events as witness observations and physical evidence. Modeled uncertainty, loss, tampering, contamination, and clock skew should be explicit rather than accidental contradictions.

## 11.2 DFIR co-pilot role

The future DFIR co-pilot should behave as a mentor or laboratory assistant, not a culprit-revealing oracle. It may:

- explain a tool or forensic concept;
- help organize findings;
- review methodology;
- point out unsupported inferences;
- assist with timelines and chain of custody;
- adapt guidance to the selected assistance profile.

It should not inspect hidden truth and simply announce the solution.

## 11.3 Possible experience modes

Longer term, the game could support experiences such as:

- **Story mode:** evidence is summarized and deductions are more explicit.
- **Investigator mode:** the player builds timelines, compares claims, and performs evidence-driven reasoning.
- **Forensic mode:** the player receives rawer synthetic artifacts, performs acquisition and analysis, and documents conclusions.

These are future design directions, not active milestone requirements.

# 12. Roadmap

## Phase 0 - Preserve the working foundation

- Correct product naming.
- Preserve and tag the current authored build.
- Keep the authored cases playable as regression fixtures.
- Document the active source of truth.

## Phase 1 - Procedural autonomous-NPC vertical slice (active)

- Structured case schema and generator.
- Case validation and rejection or repair loop.
- Immutable canonical event graph.
- Seven distinct NPC private states.
- Autonomous movement, conversation, investigation, disclosure, concealment, assistance, and misdirection.
- Bounded murderer counterplay.
- Structured accusation evaluation.
- Seeded replay and post-game audit.
- Blind sub-agent playtesting and human acceptance.

## Phase 2 - Game layer and player experience

- Difficulty dimensions and profile system.
- Curated profiles plus advanced custom controls.
- Interactive map and three-pane interface.
- Character portrait, emotion sprite, and optional voice presentation.
- Notebook, timeline, contradiction, and hypothesis tools.
- Guided onboarding or tutorial case.
- Better pacing, feedback, accessibility, and failure explanations.

## Phase 3 - Framework and content ecosystem

This phase may overlap with Phase 2 where practical.

- Broad provider abstraction.
- API and local-host adapters.
- Per-role model routing, batching, concurrency, and fallback.
- Character Card V1/V2/V3 import, normalization, editor, and export.
- Location-pack schema, validator, map editor, and packaging.
- Versioning, migrations, content safety, and creator diagnostics.
- Voice adapter and optional voice profiles.

## Phase 4 - Forensic simulation and DFIR co-pilot

- Co-design with the forensic collaborator.
- Forensic artifact compiler from canonical events.
- Chain of custody and evidence-integrity mechanics.
- Forensic workspaces and separate analysis windows.
- Training-oriented profiles and evaluation.
- DFIR co-pilot as mentor and methodology assistant.

## Phase 5 - Later expansions

- Selectable event-driven continuous simulation.
- Player-as-murderer mode.
- More complex locations and multi-scene cases.
- Additional roles, institutions, or cooperative play.
- Release hardening only when the product is ready for outside users.

# 13. Major risks and mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| A generated case is coherent but not uniquely solvable | The player can make reasonable deductions but no single culprit is best supported. | Formal validation, independent evidence paths, property tests, blind playtests, and reject/regenerate behavior. |
| Evidence exists but is not discoverable | A solver with access to truth can solve it, but a real player cannot reach the clues. | Accessibility graph, route validation, player-interface playtesting, and clue redundancy. |
| Self-confirming tests | Codex may write tests that merely encode its own mistaken interpretation. | Demonstrate pre-fix or mutation failure, use invalid fixtures, blind sub-agents, and human review. |
| NPCs hallucinate facts or leak secrets | The mystery collapses if dialogue invents or reveals canonical information. | Private state isolation, controlled prompts, structured actions, claim provenance, and engine validation. |
| NPCs become passive or all act like detectives | The world feels scripted or characters lose personal motivation. | Goal-driven planning, heterogeneous policies, social incentives, and behavior-focused playtests. |
| Murderer counterplay makes the case unfair | The killer may permanently destroy the only route to the truth. | Protected evidence redundancy, bounded action permissions, recoverability checks, and solvability revalidation. |
| The user interface leaks hidden state | Map markers, sprites, or descriptions can spoil the mystery. | Render only player perception and discovered knowledge. |
| Settings become an untestable explosion | Too many combinations create invalid or contradictory game states. | Curated profiles, subsystem presets, validation, versioning, and clear warnings for custom modes. |
| Provider-specific code contaminates the engine | Supporting new providers becomes fragile and expensive. | Capability-based adapters, standardized request and result types, and no provider logic in world rules. |
| Imported cards inject instructions | User content may manipulate prompts or bypass boundaries. | Treat cards as data, delimit content, sanitize and validate fields, and keep authority in engine code. |
| Saves and content packs break after updates | A framework needs long-lived schemas. | Versioned formats, migrations, immutable IDs, and compatibility tests. |
| Scope drift | Codex may polish, redesign, or begin future systems before proving the core. | Explicit goal boundaries, milestone acceptance reports, preserved fixtures, and human steering at checkpoints. |

# 14. Open design questions

These questions are important but do not block the active milestone:

1. What exactly occupies the left context pane by default?
2. How much free-form action input should be supported in the first polished game layer?
3. What are the first curated top-level profiles and their exact parameter bundles?
4. What minimum playtest count constitutes MVP acceptance without wasting agent budget?
5. Should all NPCs share one model by default, or should specific roles use different defaults?
6. How should model capability negotiation work across providers with different tool, JSON, reasoning, and batching support?
7. What is the first author-friendly map format and editor workflow?
8. Which voice providers and local voice options should be supported after the first adapter?
9. How should partial accusation success be scored and presented?
10. Which forensic artifacts and workflows should be prioritized after the collaborator's review?
11. How should future continuous simulation coexist with turn-based saves, replay, and profiles?
12. What distinct mechanics make player-as-murderer mode more than a role swap?

# 15. Immediate next actions

1. Enforce the product name **AI Murder Mystery Game** across product-facing text, while preserving intentional in-world names and stable fixture identifiers.
2. Set the active Codex goal from Appendix A.
3. Preserve and tag the current authored foundation.
4. Implement the structured procedural case schema, generation, and validator.
5. Compile accepted cases into immutable truth and initialize seven private NPC agent states.
6. Add bounded autonomous NPC actions and structured accusation evaluation.
7. Add seeded replay and a complete truth, action, claim, and knowledge audit.
8. Run adversarial automated tests.
9. Run blind sub-agent playtests through the player interface until the acceptance gate is met.
10. Perform at least one human blind playthrough before treating the milestone as a trustworthy MVP.
11. After acceptance, begin the settings/profile and game-interface design phase, then bring in the forensic collaborator for feedback before committing to the forensic architecture.

# Appendix A - Active Codex goal

**Goal title:** Build the Procedural Autonomous-NPC Vertical Slice for AI Murder Mystery Game

```text
Implement and verify the first procedurally generated, uniquely solvable,
autonomous-NPC vertical slice of AI Murder Mystery Game.

Use docs/product_north_star.md as the controlling specification for this
milestone.

Starting from:

- one validated location package,
- eight compatible Character Card V3 cards,
- and a deterministic seed,

the game must generate and validate a new closed-circle murder case, compile the
accepted case into immutable canonical truth, assign one selected NPC as the
victim, and initialize the seven living NPCs as autonomous agents. The player
detective is separate from the eight selected character cards.

Each living NPC must receive a genuinely distinct private state containing only
its own observations, knowledge, beliefs, secrets, relationships, goals, and
runtime memory. During play, NPCs must be able to autonomously move, converse,
exchange information, investigate, approach the player, assist, misdirect,
conceal or disclose information, and react to world events. This includes
bounded murderer counterplay.

NPCs and model providers may propose actions and dialogue, but they must never
create or modify canonical world truth. The authoritative game engine must
validate actions, resolve consequences, control evidence provenance, and judge
the final accusation.

The final accusation must evaluate:

- culprit,
- motive,
- method,
- relevant timeline,
- contradictions,
- and selected supporting evidence.

Preserve the existing authored cases as playable regression fixtures. They may
be used for regression testing, but neither authored case may be used to satisfy
the procedural acceptance criterion.

This Goal is complete only when all of the following are demonstrated:

1. At least one case is generated from a compatible cast and location rather
   than loading either fixed authored crime spine.
2. The generated case passes validation for timeline consistency, evidence
   provenance, character knowledge boundaries, means, motive, opportunity,
   clue accessibility, and a uniquely best-supported culprit.
3. The generated case remains solvable after autonomous NPC activity.
4. The case exposes at least two independent evidentiary routes to the uniquely
   best-supported culprit.
5. Deterministic seeded replay reproduces the authoritative case and resolved
   action history.
6. A complete post-game truth/action/knowledge audit is available.
7. The relevant automated test suite, production build, and end-to-end
   generated-case acceptance scenario pass.
8. The existing authored-case regression fixtures remain playable and their
   regression tests continue to pass.

Before declaring completion, produce an acceptance report containing:

- the seed,
- selected location and character cards,
- generated-case validation results,
- the two independent evidence routes,
- an autonomous-NPC action trace,
- the final accusation evaluation,
- replay/audit results,
- exact tests and commands run,
- and an honest list of remaining limitations.

Do not broaden scope beyond this milestone. Do not begin unrelated game modes,
large visual redesigns, or general polish unless required to satisfy one of the
acceptance criteria above.
```

# Appendix B - Naming correction for Codex

```text
Naming correction:

The product and project name is "AI Murder Mystery Game."

"Ashwick" is not the product name. It may remain only where it is intentionally
the in-world name of a sample location, authored case, or fixture. Replace uses
of "Ashwick" that refer to the product, application, project, build, vertical
slice, or overall game.

Do not indiscriminately rename case IDs, location content, save compatibility
identifiers, or regression fixtures merely because they contain "Ashwick."
First distinguish product-name usage from in-world content usage.
```

# Appendix C - Working terminology

| Term | Working meaning |
|---|---|
| Character card | Reusable character identity and personality data, independent of any one murder case. |
| Case overlay | Per-case role, knowledge, observations, secrets, relationships, goals, and runtime state assigned to a character. |
| Location package | Validated rooms, graph, perception rules, objects, map, art, and interaction metadata. |
| Case compiler | System that constructs a candidate murder from the selected content and seed. |
| Case validator | System that proves or rejects consistency, accessibility, fairness, and unique best support. |
| Canonical truth | Immutable authoritative facts of the murder and its causal event graph. |
| NPC agent | A living character with private state and goals that proposes bounded actions and dialogue. |
| Player perception snapshot | The exact subset of world state and events the interface is allowed to show the player. |
| Evidence route | A materially independent reasoning path from discoverable evidence to the culprit. |
| Play profile | A named bundle that selects presets across mystery, clue, NPC, simulation, assistance, accusation, runtime, and presentation systems. |
| Regression fixture | Preserved authored content used to prevent working behavior from breaking; it is not proof of procedural generation. |
