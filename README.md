# The Ashwick Trust

A local-first, turn-based murder mystery in which the rules engine owns the truth and AI is an optional performance layer. Investigate Ashwick Manor, interview its inhabitants, reconcile evidence and testimony, then make a supported accusation before time expires.

The current build is a complete playable vertical slice. It needs no API key and does not send case truth to a model.

## What is playable

- A hand-authored Ashwick Manor case with eight Character Card V3 characters.
- Discovery, room-to-room investigation, body examination, searches, evidence review, and limited interviews.
- A sourced notebook with facts, notes, timeline entries, contradictions, and suspects.
- Ten-minute deterministic turns with NPC activity resolved from one immutable turn-start snapshot.
- Versioned local JSON saves, safe resume, timeout, supported accusation, and post-game debrief.
- Optional OpenRouter dialogue portrayal constrained to claims the engine has already authorized.
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

The suite includes rules tests, transport-level truth-redaction tests, a full black-box API solve, persistence and tamper checks, constrained-AI boundary tests, and adversarial input/state-atomicity cases.

## Optional AI portrayal

The core game is deterministic. In Settings, an OpenRouter key and model can optionally be supplied to restyle an NPC's already-approved interview claim. Provider output is schema-validated, fact references are allow-listed, timeouts and malformed output fall back locally, and generated prose cannot mutate world state.

The key is stored locally in `backend/user_config.json`. Save games are stored in `backend/saves/`; both paths are ignored by Git.

## Project map

- `backend/game/` — canonical models, content loading, turn engine, public projections, saves, and portrayal boundary.
- `backend/content/` — the Ashwick case, manor, and CCv3 cards.
- `backend/routers/` — FastAPI transport.
- `frontend/` — vanilla JavaScript/Vite interface.
- `backend/tests/` — unit, contract, adversarial, and playthrough coverage.
- `docs/project_brief.md` — controlling product specification.
- `docs/mvp_decisions.md` — resolved MVP ambiguities and invariants.
- `docs/prototype_reuse_audit.md` — retained versus replaced prototype components.

## Design invariant

The engine decides facts, disclosure, actions, time, evidence, and win conditions. Models may portray authorized dialogue, but model prose is never authoritative game state.

## License

MIT
