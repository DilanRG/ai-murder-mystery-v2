# DeepSeek V4 Two-Phase Playtest Report

**Status:** Not started — DeepSeek BYOK preflight is unresolved
**Controlling evaluation:** [deepseek_v4_phase1_evaluation_report.md](deepseek_v4_phase1_evaluation_report.md)

This report intentionally separates intended play, adversarial testing, and post-fix normal regression. Empty sections are preserved so missing evidence cannot be mistaken for a pass.

## Phase A — blind intended play

Planned crossed cells:

| Cell | Generated case selection | Runtime NPC model | Status |
|---|---|---|---|
| A | First admitted Pro case in manifest order | Pro for all seven NPCs, interviews, and portrayal | Not run |
| B | Same pristine Pro case | Flash for all seven NPCs, interviews, and portrayal | Not run |
| C | First admitted Flash case in manifest order | Pro for all seven NPCs, interviews, and portrayal | Not run |
| D | Same pristine Flash case | Flash for all seven NPCs, interviews, and portrayal | Not run |

Each player receives an opaque localhost session exposing only health, bootstrap, state, action, and an empty save listing. New-game, demo, settings, model, card, save/load, OpenAPI, and debrief routes are absent. The server records only player requests and public responses, then seals the transcript before canonical audit access.

Player action transcripts, evidence/claims, evolving hypotheses, contradictions, NPC effects, final accusations, results, fairness judgements, and causal diagnoses: **no evidence yet**.

Phase A acceptance: **not evaluated**.

## Phase B — adversarial black-box play

Entry condition: all Phase A requirements must pass and budget must remain. This condition has not been met.

- Pro-NPC adversarial session: not run.
- Flash-NPC adversarial session: not run.
- Confirmed critical defects: none observed because sessions have not run.
- Confirmed major defects: none observed because sessions have not run.
- Defect fixes and falsifiable regressions: none yet.

## Post-fix intended-play regression

- Normal Pro-NPC regression: not run.
- Normal Flash-NPC regression: not run.
- Full backend/frontend/build/package/save/replay/authored regression after adversarial fixes: not run.

## Blindness limitation

The restricted server prevents accidental access through player APIs, but Codex subagents in this shared desktop workspace retain filesystem tools. Their blindness is therefore attested and auditable rather than enforced by OS isolation. This limitation must remain in the final evaluation.
