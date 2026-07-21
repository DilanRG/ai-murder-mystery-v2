# DeepSeek V4 Phase 1 Evaluation Report

**Status:** Incomplete — revision 6 preflight passed; staged generation pending
**Experiment date:** 2026-07-21 to 2026-07-22
**Product:** AI Murder Mystery Game
**Frozen input manifest:** [`backend/experiments/deepseek_v4_manifest.json`](../backend/experiments/deepseek_v4_manifest.json)

This is a live evidence report, not a Phase 1 or MVP completion claim. The experiment must ultimately stop at the human blind-playtest gate.

## Current provider result

Three revision-1 requests to `deepseek/deepseek-v4-flash` were rejected before generation. One revision-2 routing diagnostic completed through WandB and is invalidated because it did not use the required DeepSeek upstream. Two revision-3 forced-DeepSeek requests were rejected before generation because the OpenRouter account guardrail/data policy excluded the endpoint. Revision 4 then verified both direct models and complete token accounting.

The revision-4 generation diagnostic retained P1/Flash as rejected after three structurally different failures. P1/Pro used all 16,384 completion tokens for reasoning on all three attempts, returned `finish_reason=length`, and emitted no final JSON. P2/Pro repeated the same shape. Revision 5 raised the shared Pro/Flash allowance to 32,768 and fixed the final transport boundary. Its corrected P1/Flash cell then produced two full but cross-domain-inconsistent case documents followed by truncated JSON; all three were rejected. The matrix stopped before the next model cell.

Revision 6 replaces that one-shot candidate with four independently schema-validated stages: crime/facts, evidence/solution, private overlays, and public presentation. The first two prompt messages are byte-identical across stages and repairs so DeepSeek's automatic prefix cache can be measured and reused. Truth is assembled deterministically and must pass the unchanged global validator before the public-presentation stage runs.

The first revision-6 Flash and Pro preflights both verified the exact model, direct DeepSeek transport, no fallback, and complete direct token metering. They cost USD 0.00002013 total. Confirmed cumulative external spend at that checkpoint is USD 0.12922357. The ledger retains USD 1.68643580 across eight unresolved reservations. This conservative reservation is not confirmed provider spend and still leaves USD 6.18434063 before the soft stop. The corrected revision-5 one-shot baseline, including hashes, requests, diagnostics, results, and ledger snapshot, is preserved under the ignored private artifact tree.

The owner supplied a separate direct DeepSeek development key. Revision 6 has re-proved both exact models, direct transport identity, complete token accounting, and zero gateway fee. Because evidence is bound to an exact clean Git SHA, the two tiny checks will be recorded once more after this status-only commit before the revised matrix begins.

## Frozen comparison design

- Exact models: `deepseek-v4-pro` and `deepseek-v4-flash`.
- Provider route: official direct DeepSeek API; no gateway, shared-provider, or model fallback; `top_k` deliberately omitted for both models.
- Reasoning effort: high for both models. DeepSeek documents `temperature` and `top_p` as ignored in thinking mode, so revision 4 omits them from direct requests while retaining the frozen values as historical cross-route metadata.
- Three predeclared paired seeds and casts, alternating Flash/Pro order.
- One predeclared balanced reserve pair, usable only under its manifest rule.
- One candidate pipeline per model/case cell, with maximum three attempts per stage and identical Pro/Flash limits: 20,000 core, 20,000 evidence/solution, 24,000 overlays, and 8,000 public presentation tokens. Calls remain sequential and stop before downstream stages when an upstream stage exhausts its attempts. Reports distinguish candidate pipelines from chargeable stage requests.
- Soft stop USD 8.50; hard operational stop USD 9.50; USD 0.50 uncertainty reserve.
- Reservation ceilings are USD 5/M input and USD 10/M output for both models. On 2026-07-22 the direct DeepSeek endpoint advertised USD 0.14/M input and USD 0.28/M output for Flash, and USD 0.435/M input and USD 0.87/M output for Pro.
- Crossed runtime cells select the first admitted Pro case and first admitted Flash case in manifest order, never subjective favourites.

## Prepared evidence controls

- Every provider request reserves worst-case spend before transport and settles only when direct DeepSeek returns a complete cache-hit, cache-miss, and output-token meter. Cost is calculated from the frozen official price card; gateway fee is zero.
- Every request records revision, Git SHA, run/phase/pair/role, exact model, direct transport identity, accounting mode, request and generation IDs, start time, latency, token/cache/reasoning counts, external charge, finish reason, and result without prompt or private-state content.
- Every staged candidate records stage, stage-attempt number, prompt/schema revision, repair use, admission outcome, rejection category, request/generation linkage, and safe validator detail.
- Crossed play restores a pristine validated generated-save envelope. Changing NPC model cannot regenerate or edit canonical truth.
- All seven NPC, interview-selection, and portrayal calls use the cell’s assigned runtime model. A concurrency-one wrapper serializes the production coordinator’s seven coroutines.
- Deterministic fallback is classified separately as timeout, malformed response, invalid action/response ID, provider error, or provider unavailable; it is never counted as model success.
- Phase A uses a restricted localhost player API and append-only, SHA-256-sealed public transcript. Canonical truth and debrief remain unavailable until the transcript and player report are frozen.

## Results

| Evidence area | Pro | Flash |
|---|---:|---:|
| Confirmed direct DeepSeek preflight | Revision 6 passed on staged code checkpoint | Revision 6 passed on staged code checkpoint |
| Paired generation cells attempted | Revision-4 diagnostic: P1 rejected; P2 interrupted | Revision-4 P1 rejected; corrected revision-5 P1 rejected |
| Admitted cases | 0 | 0 |
| Crossed intended-play cells | 0 / 2 | 0 / 2 |
| Adversarial sessions | 0 / 1 | 0 / 1 |
| Measured external cost | USD 0.07093663 revision-4 direct diagnostic | USD 0.03918754 across revision-4 and corrected revision-5 generation diagnostics |

Generation quality, NPC quality, latency, cache behaviour, cost per case/turn/interview/game, and qualitative model comparisons are not yet measurable. No routing recommendation is justified yet.

## Verification completed at this checkpoint

```text
python -m pytest backend\tests -q -p no:cacheprovider
381 passed, 20 warnings

npm.cmd test -- --test-reporter=spec
16 passed

npm.cmd run build
Vite production build succeeded; 11 modules transformed

python build\build.py --skip-frontend
Windows package built (17.8 MB); packaged smoke passed
```

Provider tests remain explicitly opt-in. The ordinary suite makes no paid calls.

## Remaining work

1. Re-record both tiny direct DeepSeek preflights against the final status-only Git SHA.
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
