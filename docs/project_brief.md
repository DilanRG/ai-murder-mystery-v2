# Project Brief: AI-Driven Murder Mystery Game

## Current Source of Truth

Use this brief as the current plan for the project. The existing prototype is approximately six or seven months old and will require a major redesign. When the prototype becomes available, inspect it before deciding what can be reused. Where the old prototype or design document conflicts with this brief, this brief takes precedence.

## Core Concept

Build a replayable, AI-driven, closed-circle murder mystery game inspired by stories such as *Murder on the Orient Express* and other isolated-location mysteries.

Each game takes place inside a contained location—for example, an island mansion, stranded hotel, moving train, yacht, or remote research station. The player is the detective. Eight NPC characters are involved in the case:

- One NPC is the victim.
- Seven NPCs remain alive and operate as AI agents.
- One living NPC is the murderer.
- Six living NPCs are innocent suspects with their own secrets and motivations.
- The player is the detective and is separate from the eight NPCs.

Murderer mode is explicitly out of scope for the MVP. It may be added in a later update.

## Start of the Game

The game starts after the murder has already occurred.

The pre-murder timeline is generated and stored as canonical case data, but it is not simulated live during the MVP.

Opening sequence:

1. A living character discovers the victim.
2. They raise the alarm.
3. Everyone gathers in a predefined assembly area.
4. The discoverer explains only what they actually observed.
5. The isolation or containment situation is established.
6. The surviving characters provide short initial reactions or statements.
7. The player is placed in charge of the investigation.
8. The meeting concludes, the characters disperse, and the turn-based simulation begins.

The discovery meeting is structured by the game engine. The LLM may express the characters’ reactions, but it cannot invent the body’s condition, discovery time, evidence, witnesses, or other case facts.

The discoverer can potentially be the murderer if the generated case supports a staged discovery.

## Time and Turn System

The MVP uses turn-based time. Continuous real-time simulation is deferred until after the turn-based version works reliably.

A normal investigation turn consists of:

1. The player chooses an action:
   - Move to another room
   - Search a room or object
   - Interview a character
   - Examine evidence
   - Review notes, statements, or the timeline
   - Perform another validated investigation action
2. The action consumes investigation time.
3. The NPC phase runs:
   - Characters move or act according to their goals.
   - Characters may speak privately.
   - The murderer may take permitted defensive actions.
   - Emotional states and suspicions change.
   - Scheduled or triggered events may occur.
4. The authoritative game state is updated.

An interview should normally count as one investigation action or turn, rather than charging time for every individual chat message.

## Authoritative World Model

The AI agents inhabit the world but do not author reality.

The system must maintain separate layers for:

- Immutable ground truth
- Current world state
- Each character’s observations and knowledge
- Each character’s beliefs and suspicions
- Statements and claims made during dialogue
- Player-discovered information

The canonical murder history never changes after the case is generated. The present world can change only through actions validated by the game engine.

An AI agent cannot create evidence, change rooms, acquire objects, witness events, or establish facts through narration. It can only request actions through a controlled interface. The engine approves or rejects the action and updates the state.

LLM responsibilities:

- Portray the assigned character
- Generate natural dialogue
- Decide what the character wants to attempt
- Conceal, reveal, distort, or lie about information when appropriate
- React emotionally and socially
- Reason using the character’s restricted knowledge

Game-engine responsibilities:

- Own the map, timeline, evidence, inventory, movements, and case truth
- Decide what each character can perceive
- Validate all actions
- Record events and conversations
- Prevent contradictions and unauthorized world changes
- Determine whether the case remains solvable

## Case Generation

Cases must be assembled from structured, predefined components rather than generated freely by an LLM.

A generated case includes:

- Victim and murderer assignments
- Motive, method, means, and opportunity
- Exact murder timeline
- Character schedules
- Relationships
- Private secrets
- True, false, and incomplete alibis
- Physical, testimonial, and documentary evidence
- Witness observations
- Red herrings with valid explanations
- A logical path to identifying the murderer

Every generated case must pass validation before play begins. The validator should ensure:

- The timeline is internally possible.
- Evidence does not contradict the ground truth.
- Character knowledge matches their observations.
- The murderer had means, motive, and opportunity.
- Innocent suspects remain plausible without becoming equally valid solutions.
- There is enough independent evidence to solve the case.
- The intended murderer is the unique best-supported culprit.

## Character Card System

Characters are not loose archetype frameworks. Each character is a complete reusable package based on Character Card V3 and optimized for this game.

Use three separate character layers:

### 1. Game Character Card — Reusable Across Cases

Contains:

- Name and identity
- Description and appearance
- Portrait and expression assets
- Personality
- Speaking style
- Example dialogue
- Background and public biography
- Values, fears, habits, flaws, and vulnerabilities
- Social and conflict behaviour
- Deception and disclosure tendencies
- Emotional response rules
- Relationship compatibility
- Possible motive and secret hooks
- Character-specific lorebook
- Game-specific behavioural constraints

### 2. Case Overlay — Generated for One Mystery

Contains:

- Victim, murderer, or innocent assignment
- Relationships in the current cast
- Current secrets and motives
- Pre-murder schedule
- Actual observations
- Knowledge of the victim
- Alibi and supporting evidence
- Case-specific goals
- Information the character is willing to hide or lie about

### 3. Runtime State — Changes During Play

Contains:

- Current location
- Current activity
- Emotional state
- Suspicion toward other characters
- Conversation memory
- Lies and claims already made
- Known evidence
- Information received from others
- Inventory
- Current intentions and plans

Victim or murderer status must never be permanently embedded in the reusable card.

Preserve genuine CCv3 compatibility where practical. Store game-specific static fields inside an extension namespace such as `extensions.murder_mystery`.

Character-card content is subordinate to global game rules. Imported system prompts, lorebook entries, or instructions must never be allowed to override the authoritative world model, reveal hidden state, or bypass action validation.

A generic CCv3 card may be imported as a starting point, but it must pass through a game-card editor and validation process before becoming playable.

## Location Packages

Locations must also be predefined, structured packages rather than unrestricted LLM creations.

A location package contains:

- Fixed map
- Rooms and valid movement routes
- Assembly room
- Potential body-discovery locations
- Doors, locks, keys, and access restrictions
- Searchable objects
- Potential weapons and evidence slots
- Character movement constraints
- Isolation premise
- Location-specific events
- Thematic visual assets
- Rules defining valid murder opportunities

The case generator selects from compatible possibilities inside the location package. The LLM may describe the environment but cannot invent new rooms, exits, objects, or evidence.

## UI and Interaction Design

The product should have a modern, attractive, interactive game interface.

*Degrees of Lewdity* is a reference for the basic interaction rhythm:

- Read the current passage or scene.
- Inspect persistent information.
- Select contextual actions.
- Advance the game state.
- Receive the next passage.

Do not copy its visual design directly. Create a more polished, customized interface appropriate for a cinematic murder mystery.

Preferred desktop layout:

- **Top bar:** Current location, investigation turn, in-game time, case title, save/settings controls
- **Left panel:** Interactive location map, available rooms, movement controls
- **Centre:** Scene presentation, narration, character portraits, dialogue, discoveries, contextual actions
- **Right panel:** Present characters, suspect shortcuts, recent evidence, notebook indicators
- **Bottom interaction area:** Free-text dialogue input, suggested questions, and scene-specific action buttons

Important interactive features:

- Clickable rooms and routes
- Character portraits with expression changes
- Expandable character dossiers
- Free-text interrogation
- Suggested question and action chips
- Searchable objects and room hotspots
- Evidence board
- Player-built timeline
- Statement comparison and contradiction marking
- Investigation notebook
- New-information indicators
- Final accusation interface covering culprit, motive, method, and timeline

The UI must display only information the player has legitimately learned.

The game must not look like seven separate chatbot windows. Dialogue is one activity within the larger investigation game.

## Visual Direction

Use a modern cinematic-noir foundation:

- Deep charcoal or midnight surfaces
- Warm ivory text
- Muted brass or gold accents
- Burgundy for danger and contradictions
- Strong character portraits
- Clean typography
- Restrained animations and transitions
- Location-specific backgrounds and colour accents

Each location may have a distinct theme while retaining the same functional interface.

## Delivery Format

Build the MVP as a responsive web application first.

Design it so that the same application can later be:

- Installed as a PWA
- Hosted as a web application
- Bundled with its local backend as a standalone executable

Avoid developing separate desktop and web versions.

## MVP Non-Goals

Do not include these in the initial implementation:

- Player murderer mode
- Continuous real-time simulation
- Live pre-murder simulation
- Completely freeform LLM-generated locations
- Completely freeform LLM-generated characters
- Unvalidated procedural mysteries
- Agents capable of changing reality through narration
- A chatbot-only interface
- Monetization or energy systems

## First Playable Vertical Slice

The first complete build should contain:

- One polished isolated location
- Eight validated Game Character Cards
- One player detective
- One victim and seven living AI characters
- Structured case generation
- Case-solvability validation
- Body-discovery opening meeting
- Turn-based investigation
- Room navigation and searching
- Constrained character interviews
- Persistent character memory
- Evidence collection
- Basic evidence board and timeline
- Final accusation and result
- Save/load support
- Responsive modern web UI

## Implementation Order

1. Inspect the existing prototype when available.
2. Decide what can be safely reused.
3. Define the Game Character Card, case overlay, runtime state, location, evidence, and timeline schemas.
4. Build a deterministic sample case without an LLM.
5. Build the case validator.
6. Implement the turn and world-state engine.
7. Build the discovery meeting and investigation loop.
8. Build the modern UI shell.
9. Add character-card loading and validation.
10. Add the constrained LLM dialogue and action layer.
11. Complete and test one vertical slice.
12. Add procedural case assembly.
13. Optimize calls, context, persistence, and packaging.

## Open Design Decisions

Do not silently choose these without discussion:

- First location
- Exact turn duration and action economy
- Final technical stack
- Hosted versus local backend requirements
- Supported LLM providers
- How NPC turns are batched
- Exact accusation scoring
- Portrait and expression asset pipeline
- Extent of murderer evidence manipulation
- CCv3 import/export formats required for the MVP

## Working Style

Proceed in small checkpoints. Surface interpretations and architectural decisions early before implementing large sections. Preserve existing user files and changes. Do not perform destructive actions or replace parts of the prototype without explicit approval and exact target verification.
