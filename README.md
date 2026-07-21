# The Ashwick Trust

[![Verify packaged game](https://github.com/DilanRG/ai-murder-mystery/actions/workflows/verify-packages.yml/badge.svg)](https://github.com/DilanRG/ai-murder-mystery/actions/workflows/verify-packages.yml)

A local-first, turn-based murder mystery in which OpenRouter generates a new canonical case from a selected cast and location, then the rules engine owns and enforces that truth. Investigate Ashwick Manor, interview its inhabitants, reconcile evidence and testimony, then make a supported accusation before time expires.

Normal **New Story** generation requires an OpenRouter API key. Two clearly labelled offline demo fixtures remain available for development, automated testing, and provider outages; they are not substitutes for the generation engine.

## What is playable

- Automatic or manual selection of any eight characters from the 24-card pool, followed by validated OpenRouter generation of the roles, timeline, murder, evidence, private overlays, solution, and public framing.
- Two complete authored Ashwick Manor demo mysteries for deterministic implementation and offline testing.
- Twenty-four Character Card V3 characters plus a local JSON import, validation, draft, and export editor.
- Discovery, room-to-room investigation, body examination, searches, evidence review, and limited interviews.
- A sourced notebook with facts, notes, timeline entries, contradictions, and suspects.
- Ten-minute deterministic turns with NPC activity resolved from one immutable turn-start snapshot, including bounded private exchanges and evolving suspicion.
- Replay-verified v2 local JSON saves, safe legacy-v1 resume, timeout, supported accusation, and post-game debrief.
- Seven separately partitioned living-NPC planning calls per committed generated-story turn. Each receives one byte-bounded private briefing plus the same immutable public snapshot and may select only its own engine-authored action ID for movement, holding, permitted evidence defense, or an unobserved social choice.
- Private social choices can state an alibi, share an observation the speaker actually knows, make a pre-authorized lie, or react without asserting a fact. Truthful observations transfer only their linked fact IDs to one co-located listener; lies never become facts.
- Optional bounded dialogue portrayal after the engine has committed an authorized claim.
- Distinct, versioned noir portrait placeholders for the full cast, with accessible text fallbacks.
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

The build produces `dist/ai-murder-mystery.exe` on Windows (or the corresponding extensionless binary on macOS/Linux). A build is considered successful only after the produced executable starts headlessly, loads all 24 characters and both authored cases, advances a turn, and writes and reloads a v2 save. Use `--skip-frontend` only when `backend/static` is already current; `--skip-smoke` is available for build diagnostics, not release publishing.

## Test

```powershell
cd backend
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

The automated suite contains 237 Python tests plus ten dependency-free frontend boundary tests. It covers rules, transport-level truth redaction, generated-case admission and retry, full solve paths for both authored dummy mysteries, every pooled card solved against both dummy spines, 24-card cast reachability, manual/automatic start contracts, recipe reproducibility, generated-case save/restore, replay and tamper checks, seven-way private NPC isolation, bounded social knowledge transfer, constrained-AI boundaries, concurrent cancellation, release contracts, and adversarial input/state-atomicity cases. New boundaries are developed red-to-green and selectively mutation-tested so a passing test has demonstrated that it can catch the regression it claims to cover.

## OpenRouter generation and agent boundary

In Settings, supply an OpenRouter key and model before choosing **Generate new mystery**. The selected eight Character Card V3 profiles and the predefined location package are sent to one scenario-generation call. The host injects IDs and turn policy, parses the result into strict schemas, and rejects it unless chronology, discovery routes, prerequisite reachability, evidence placement, red-herring bounds, reciprocal solution links, and unique solvability all validate. A failed generation never replaces the currently active game.

Once admitted, that immutable case spawns seven private NPC contexts: the victim is excluded, the murderer alone receives the crime truth, and no living agent receives another character's motive, secrets, or private memory. On each committed turn the seven calls run independently against the same frozen snapshot. A response can contain only one semantically bound, allow-listed action ID; malformed, stale, timed-out, or out-of-set responses fall back independently without breaking the turn. Interview wording can also be portrayed after the engine has selected and recorded the underlying authorized facts.

Generated cases are saved with their canonical truth and a content fingerprint, then fully revalidated and replay-checked on restore without another provider call. Provider output never receives an arbitrary state-patch interface or authority to mutate rooms, evidence, facts, or tools.

Automated and initial integration tests use an in-process dummy provider and spend no OpenRouter credits. Real-provider playtesting is the next validation stage after the deterministic suite is stable.

In a source checkout, the key is stored locally in `backend/user_config.json`, save games in `backend/saves/`, and imported card drafts in `backend/card_drafts/`; all three paths are ignored by Git. Packaged builds use durable per-user data instead of PyInstaller's temporary extraction folder: `%LOCALAPPDATA%\AshwickTrust` on Windows, `~/Library/Application Support/Ashwick Trust` on macOS, and `$XDG_DATA_HOME/ashwick-trust` (or `~/.local/share/ashwick-trust`) on Linux. Set `ASHWICK_TRUST_DATA_DIR` to use an explicit portable location.

## Project map

- `backend/game/` — generated-case admission, canonical models, private NPC boundaries, turn engine, public projections, saves, card library, and portrayal boundary.
- `backend/content/` — two offline demo cases, the structured manor location, and 24 CCv3 cards.
- `backend/routers/` — FastAPI transport.
- `frontend/` — vanilla JavaScript/Vite interface.
- `backend/tests/` — unit, contract, adversarial, and playthrough coverage.
- `docs/project_brief.md` — controlling product specification.
- `docs/mvp_decisions.md` — resolved MVP ambiguities and invariants.
- `docs/prototype_reuse_audit.md` — retained versus replaced prototype components.

Current completion and remaining-work notes live in [docs/active_status.md](docs/active_status.md).

## Design invariant

The engine decides facts, disclosure, valid action candidates, time, evidence, and win conditions. Models may portray authorized dialogue or select among finite authorized intents, but model output is never authoritative game state.

## License

MIT
