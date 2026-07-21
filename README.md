# AI Murder Mystery Game

[![Verify packaged game](https://github.com/DilanRG/ai-murder-mystery-v2/actions/workflows/verify-packages.yml/badge.svg)](https://github.com/DilanRG/ai-murder-mystery-v2/actions/workflows/verify-packages.yml)

A local-first, turn-based murder mystery in which OpenRouter generates a new canonical case from a selected cast and location, then the rules engine owns and enforces that truth. Investigate Ashwick Manor, interview its inhabitants, reconcile evidence and testimony, then make a supported accusation before time expires.

Normal **New Story** generation requires an OpenRouter API key. Two clearly labelled offline demo fixtures remain available for development, automated testing, and provider outages; they are not substitutes for the generation engine.

The first provider-shaped procedural case has passed the technical generation, autonomy, solvability, replay, and audit gate. The broader Phase 1 milestone remains active pending materially varied generated cases, blind interface-only agent playthroughs, and a human blind playthrough. See [Active Build Status](docs/active_status.md) for the exact boundary.

## What is playable

- Automatic or manual selection of any eight characters from the 24-card pool, followed by four-stage validated OpenRouter generation of the crime/facts, evidence/solution, private overlays, and public framing.
- Generated cases must expose at least two disjoint, complete method/motive/opportunity/timeline evidence routes to one uniquely best-supported culprit before they can become canonical truth.
- Provider-free authored-projection regression cases exercise four automatic ensembles covering all 24 cards plus an arbitrary manual ensemble through the same admission boundary, full investigation, save/load, scheduled event, solution, and timeout paths. They intentionally reuse an Ashwick crime spine and do not satisfy the procedural-case acceptance milestone.
- Two complete authored Ashwick Manor demo mysteries for deterministic implementation and offline testing.
- Twenty-four Character Card V3 characters plus a local JSON import, validation, draft, and export editor.
- Discovery, room-to-room investigation, body examination, searches, evidence review, and limited interviews.
- A sourced notebook with facts, notes, timeline entries, host-confirmed contradictions, and suspects.
- Ten-minute deterministic turns with exact-once authored location events and NPC activity resolved from one immutable turn-start snapshot, including bounded private exchanges and evolving suspicion.
- Replay-verified v5 local JSON saves, safe legacy-v1/v2/v3/v4 resume, a first-class timeout outcome, supported accusation, and post-game debrief. A checked-in save emitted by the preserved v4 foundation proves positional `option_XX` NPC histories still replay under their historical rules before upgrading to v5.
- Seven separately partitioned living-NPC planning calls per committed generated-story turn. Each receives one byte-bounded private briefing plus the same immutable public snapshot and may select only its own engine-authored action ID for movement, investigation, approach, player assistance/misdirection, world-event reaction, bounded evidence defense, or an unobserved social choice.
- Private social choices can state an alibi, share an observation the speaker actually knows, make a pre-authorized lie, or react without asserting a fact. Truthful observations transfer only their linked fact IDs to one co-located listener; lies never become facts.
- Generated-case interviews give only the target NPC its private briefing and a finite set of engine-authored alibi, truthful-observation, authorized-lie, and evasion IDs. Its selected canonical claim is recorded and replayable; optional bounded portrayal runs only after that claim has committed.
- Distinct, versioned noir portrait placeholders for the full cast, with accessible text fallbacks.
- Six-dimension final accusation evaluation covering culprit, method, motive, timeline, a complete selected evidence route, and confirmed contradictions, with the component verdict shown in the browser result.
- A complete post-game canonical-truth, NPC-action, final-knowledge, and replay-verification audit through the debrief API.
- Responsive desktop and mobile browser UI.

## Run locally

Requirements: Python 3.12+ and Node.js 20+.

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt

cd ..\frontend
npm install
npm run build

cd ..\backend
python -m uvicorn main:app --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The production frontend is built into `backend/static`; Vite development mode is also available with `npm run dev` from `frontend`.

## Build the executable

From the repository root, after installing the backend dependencies:

```powershell
.\backend\.venv\Scripts\python.exe build\build.py
```

The build produces `dist/ai-murder-mystery.exe` on Windows (or the corresponding extensionless binary on macOS/Linux). A build is considered successful only after the produced executable starts headlessly, loads all 24 characters and both authored cases, advances a turn, and writes and reloads a v5 save. Use `--skip-frontend` only when `backend/static` is already current; `--skip-smoke` is available for build diagnostics, not release publishing.

## Test

```powershell
cd backend
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

The automated suite contains 380 Python tests plus 16 dependency-free frontend behavior tests. It covers rules, transport-level truth redaction, staged generated-case admission and repair, cache-prefix stability, public-spoiler rejection, an independent non-authored procedural solve after autonomous activity, two-route solvability, cross-route accusation coherence, complete participant-aware audit/replay, full solve paths for both authored demo mysteries, every pooled card solved against both authored spines, 24-card cast reachability, manual/automatic start contracts, recipe reproducibility, generated-case save/restore, golden legacy-v4 positional replay plus legacy-v2/v3 migration, seven-way private NPC isolation, bounded social knowledge transfer, target-only interview selection, constrained-AI boundaries, concurrent cancellation, release contracts, and adversarial input/state-atomicity cases. New boundaries are developed red-to-green and selectively mutation-tested so a passing test has demonstrated that it can catch the regression it claims to cover.

## OpenRouter generation and agent boundary

In Settings, supply an OpenRouter key and model before choosing **Generate new mystery**. The selected eight Character Card V3 profiles and predefined location package pass through four bounded generation calls: crime/facts, evidence/solution, private overlays, then public presentation. Each call shares the same cache-stable prompt prefix, validates before the next begins, and retries only its rejected stage. The host derives reciprocal fact/evidence links, injects IDs, turn policy, and player-facing opening prose, then rejects assembled truth unless chronology, participant locations, private-knowledge provenance, discovery routes, prerequisite reachability, evidence placement, red-herring bounds, non-contradictory implication/exoneration, reciprocal solution links, and unique solvability all validate. Public presentation is requested only after truth admission. A failed generation never replaces the currently active game.

Once admitted, that immutable case spawns seven private NPC contexts: the victim is excluded, the murderer alone receives the crime truth, and no living agent receives another character's motive, secrets, or private memory. On each committed turn the seven calls run independently against the same frozen snapshot. A response can contain only one semantically bound, allow-listed action ID; malformed, stale, timed-out, or out-of-set responses fall back independently without breaking the turn.

An interview uses a separate target-only selection request: the NPC sees its question, private briefing, runtime state, and at most eight canonical response choices. It returns one response ID, never prose or a state patch. IDs are bound to the exact question/session exchange, hidden observations are excluded, declared alibi/lie disclosures cannot intersect hidden facts, and only a selected truthful observation grants its fact IDs to the player. Provider-authored murderer alibi/lie prose never crosses this player-facing boundary; generated murderers receive engine-authored defensive choices instead. The separate portrayal pass may reword a committed claim but cannot change it.

Generated cases are saved with their canonical truth and a content fingerprint, then fully revalidated and replay-checked on restore without another provider call. Provider output never receives an arbitrary state-patch interface or authority to mutate rooms, evidence, facts, or tools.

Automated and integration tests use an in-process dummy provider and spend no OpenRouter credits. Real-provider playtesting is explicitly on hold; it will begin only when that hold is lifted.

In a source checkout, the key is stored locally in `backend/user_config.json`, save games in `backend/saves/`, and imported card drafts in `backend/card_drafts/`; all three paths are ignored by Git. Packaged builds use durable per-user data instead of PyInstaller's temporary extraction folder: `%LOCALAPPDATA%\AshwickTrust` on Windows, `~/Library/Application Support/Ashwick Trust` on macOS, and `$XDG_DATA_HOME/ashwick-trust` (or `~/.local/share/ashwick-trust`) on Linux. Set `ASHWICK_TRUST_DATA_DIR` to use an explicit portable location.

## Project map

- `backend/game/` — generated-case admission, canonical models, private NPC boundaries, turn engine, public projections, saves, card library, and portrayal boundary.
- `backend/content/` — two offline demo cases, the structured manor location, and 24 CCv3 cards.
- `backend/routers/` — FastAPI transport.
- `frontend/` — vanilla JavaScript/Vite interface.
- `backend/tests/` — unit, contract, adversarial, and playthrough coverage.
- `docs/product_north_star.md` — controlling invariant product direction.
- `docs/AI_Murder_Mystery_Game_Design_Roadmap.md` — living systems design, sequencing, testing strategy, and acceptance gates.
- `docs/decision_log.md` — canonical short record of settled product and architecture decisions.

Superseded plans, architecture notes, and foundation decision records are preserved on the repository's [`archived` branch](https://github.com/DilanRG/ai-murder-mystery-v2/tree/archived/docs), not in the active code branch.

Current completion and remaining-work notes live in [docs/active_status.md](docs/active_status.md).
The first procedural technical-gate evidence is recorded in [docs/procedural_acceptance_report.md](docs/procedural_acceptance_report.md); it is not the full Phase 1 playtest acceptance gate.

## Design invariant

The engine decides facts, disclosure, valid action candidates, time, evidence, and win conditions. Models may portray authorized dialogue or select among finite authorized intents, but model output is never authoritative game state.

## License

MIT
