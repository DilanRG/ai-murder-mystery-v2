# DeepSeek V4 Phase 1 Evaluation Report

**Status:** Incomplete — direct-DeepSeek experiment revision 3 awaiting preflight
**Experiment date:** 2026-07-21 to 2026-07-22
**Product:** AI Murder Mystery Game
**Frozen input manifest:** [`backend/experiments/deepseek_v4_manifest.json`](../backend/experiments/deepseek_v4_manifest.json)

This is a live evidence report, not a Phase 1 or MVP completion claim. The experiment must ultimately stop at the human blind-playtest gate.

## Current provider result

Three revision-1 requests to `deepseek/deepseek-v4-flash` were rejected before generation. One revision-2 routing diagnostic completed through WandB and is invalidated because it did not use the required DeepSeek upstream. The Pro preflight was not attempted. No case generation, NPC, interview, portrayal, intended-play, or adversarial provider traffic followed.

Official OpenRouter documentation confirms that `provider.only`, `allow_fallbacks=false`, and `require_parameters=true` are the correct controls, while “Always use for this provider” prevents a prioritized BYOK key from falling back to shared capacity. Authenticated endpoint metadata confirms the exact provider tag is `deepseek`. It also isolates the revision-1 defect: the direct V4 endpoints support every measured control except `top_k`, so that parameter left no eligible endpoint. Revision 3 omits it only in the measured adapter and retains all strict routing controls.

The WandB diagnostic cost USD 0.00000490 and is settled in the private ledger. The ledger conservatively retains USD 0.00016230 for the three revision-1 requests because they produced no trusted generation accounting. The extra owner-authorized endpoint-diagnostic allowance remains effectively unused.

The owner supplied and dashboard-tested a fresh DeepSeek BYOK key through OpenRouter. Revision 3 must still prove the dated model resolution, upstream provider, BYOK flag, token data, upstream cost, and OpenRouter fee through the production adapter before substantive traffic begins.

## Frozen comparison design

- Exact models: `deepseek/deepseek-v4-pro` and `deepseek/deepseek-v4-flash`.
- Gateway route: OpenRouter with only the `deepseek` provider allowed; shared/provider/model fallback disabled; all sent parameters required; `top_k` deliberately omitted for both models.
- Reasoning effort: high for both models.
- Three predeclared paired seeds and casts, alternating Flash/Pro order.
- One predeclared balanced reserve pair, usable only under its manifest rule.
- Maximum three production admission attempts per model/case cell.
- Soft stop USD 8.50; hard operational stop USD 9.50; USD 0.50 uncertainty reserve.
- Reservation ceilings are USD 5/M input and USD 10/M output for both models. On 2026-07-22 the direct DeepSeek endpoint advertised USD 0.14/M input and USD 0.28/M output for Flash, and USD 0.435/M input and USD 0.87/M output for Pro.
- Crossed runtime cells select the first admitted Pro case and first admitted Flash case in manifest order, never subjective favourites.

## Prepared evidence controls

- Every provider request reserves worst-case spend before transport and settles only from trusted upstream cost plus OpenRouter fee data.
- Every request records revision, Git SHA, run/phase/pair/role, exact model, serving provider, BYOK/accounting mode, request and generation IDs, start time, latency, token/cache/reasoning counts, inclusive external charge, finish reason, and result without prompt or private-state content.
- Every case candidate records attempt number, prompt/schema revision, repair use, admission outcome, rejection category, request/generation linkage, and safe validator detail.
- Crossed play restores a pristine validated generated-save envelope. Changing NPC model cannot regenerate or edit canonical truth.
- All seven NPC, interview-selection, and portrayal calls use the cell’s assigned runtime model. A concurrency-one wrapper serializes the production coordinator’s seven coroutines.
- Deterministic fallback is classified separately as timeout, malformed response, invalid action/response ID, provider error, or provider unavailable; it is never counted as model success.
- Phase A uses a restricted localhost player API and append-only, SHA-256-sealed public transcript. Canonical truth and debrief remain unavailable until the transcript and player report are frozen.

## Results

| Evidence area | Pro | Flash |
|---|---:|---:|
| Confirmed DeepSeek BYOK preflight | Not run | Revision 1 failed; revision-2 WandB diagnostic invalidated |
| Paired generation cells attempted | 0 / 3 | 0 / 3 |
| Admitted cases | 0 | 0 |
| Crossed intended-play cells | 0 / 2 | 0 / 2 |
| Adversarial sessions | 0 / 1 | 0 / 1 |
| Measured external cost | USD 0.00 | USD 0.00 observed |

Generation quality, NPC quality, latency, cache behaviour, cost per case/turn/interview/game, and qualitative model comparisons are not yet measurable. No routing recommendation is justified yet.

## Verification completed at this checkpoint

```text
python -m pytest backend\tests -q -p no:cacheprovider
363 passed, 20 warnings

npm.cmd test -- --test-reporter=spec
16 passed

npm.cmd run build
Vite production build succeeded; 11 modules transformed
```

Provider tests remain explicitly opt-in. The ordinary suite makes no paid calls.

## Remaining work

1. Commit revision 3 and rerun both tiny DeepSeek-upstream preflights.
2. Attempt all six frozen paired generation cells, retaining all rejections.
3. Select first admitted Pro/Flash cases and run crossed cells A–D with independent blind player agents.
4. Freeze Phase A transcripts and reports, then inspect post-game audits and determine whether Phase A passes.
5. Only after Phase A passes, run one Pro-NPC and one Flash-NPC adversarial black-box session.
6. Fix any in-scope critical/major defects, rerun affected cells and normal Pro/Flash play, and complete build/package/save/replay regressions.
7. Conduct masked independent qualitative evaluation, unmask, calculate role-specific cost profiles, and append the provisional routing decision.
8. Stop and hand the build to a real human for the required blind playthrough.

## Limitations

- The current sample contains no successful real-provider response.
- Shared Codex subagents can technically access the workspace. The restricted HTTP handoff provides blindness by explicit access contract and transcript evidence, not operating-system isolation. A separate container/user with no workspace mount is required for hard isolation.
- Codex development and player-subagent compute are excluded from the DeepSeek external API budget.
