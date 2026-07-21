# The Ashwick Trust

A local-first, turn-based murder mystery in which the rules engine owns the truth and AI is an optional performance layer. Investigate Ashwick Manor, interview its inhabitants, reconcile evidence and testimony, then make a supported accusation before time expires.

The current build is a complete playable vertical slice. It needs no API key and does not send case truth to a model.

## What is playable

- Two complete, hand-authored Ashwick Manor crime spines selected reproducibly from a player-visible seed.
- Eight Character Card V3 characters plus a local JSON import, validation, draft, and export editor.
- Discovery, room-to-room investigation, body examination, searches, evidence review, and limited interviews.
- A sourced notebook with facts, notes, timeline entries, contradictions, and suspects.
- Ten-minute deterministic turns with NPC activity resolved from one immutable turn-start snapshot, including bounded private exchanges and evolving suspicion.
- Replay-verified v2 local JSON saves, safe legacy-v1 resume, timeout, supported accusation, and post-game debrief.
- Optional OpenRouter dialogue portrayal and NPC intent selection, both constrained to choices the engine has already authorized.
- Distinct, versioned noir portrait placeholders for the full cast, with accessible text fallbacks.
- Responsive desktop and mobile browser UI.

## Run locally

Requirements: Python 3.12+ and Node.js 20+.

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

cd ..\frontend
npm install
npm run build

cd ..\backend
python -m uvicorn main:app --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The production frontend is built into `backend/static`; Vite development mode is also available with `npm run dev` from `frontend`.

## Test

```powershell
cd backend
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

The 133-test suite includes rules tests, transport-level truth-redaction tests, full solve paths for both authored mysteries, recipe reproducibility, replay and tamper checks, constrained-AI boundaries, concurrent cancellation, and adversarial input/state-atomicity cases. New boundaries are developed red-to-green and selectively mutation-tested so a passing test has demonstrated that it can catch the regression it claims to cover.

## Optional AI layer

The core game is deterministic. In Settings, an OpenRouter key and model can optionally be supplied for two bounded jobs:

- Restyle an already-approved interview claim in character voice.
- Select one opaque, engine-authored NPC action option for each living character in a single turn batch.

Provider output is schema-validated, dialogue fact references and action IDs are allow-listed, timeouts and malformed output fall back locally, and generated output cannot mutate world state. The provider receives neither an arbitrary state-patch interface nor authority to invent rooms, evidence, facts, or tools.

The key is stored locally in `backend/user_config.json`. Save games are stored in `backend/saves/`, and imported card drafts in `backend/card_drafts/`; all three paths are ignored by Git.

## Project map

- `backend/game/` — canonical models, seeded recipes, turn engine, public projections, saves, card library, and portrayal boundary.
- `backend/content/` — two Ashwick cases, their assembly recipe, the manor, and CCv3 cards.
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
