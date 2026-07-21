# Procedural Vertical Slice Acceptance Report

**Date:** 2026-07-21
**Result:** Accepted
**Provider credits:** None; the acceptance provider is an in-process dummy
**Authored foundation:** preserved at commit `761193a55828772ec7668190c8a010b2f51ee841` and tag `ashwick-authored-foundation-v1`

## Generated case

- Seed: `731`
- Location: Ashwick Manor (`ashwick_manor`)
- Generated case ID: `generated_c2acd0bee83e389ba40c54db`
- Canonical fingerprint: `36c5afef1ed87b4bad03bd7ae194a29e6359d19c72026dd148c8a40fbd9312bf`
- Source: a deep copy of `independent_generated_document()` plus one explicit authorized clock lie for contradiction evaluation, returned through the production New Story generation boundary. It does not load, copy, project, or remap `ashwick_sample` or `ashwick_quiet_vow`. The provider supplies opening structure only; the compiler authors the player-facing discovery and reaction prose.

Selected Character Card V3 cast:

| Character | Runtime role |
|---|---|
| Captain Marcus Drake (`captain_marcus_drake`) | Victim |
| Gabriel Cross (`gabriel_cross`) | Murderer |
| Celia Marlowe (`celia_marlowe`) | Living innocent |
| Chef Armand Dubois (`chef_armand_dubois`) | Living innocent |
| Commander Elias Ward (`commander_elias_ward`) | Living innocent |
| Countess Beatrice Harrow (`countess_beatrice_harrow`) | Living innocent |
| Dr Amara Sen (`dr_amara_sen`) | Living innocent |
| Inspector Maeve Quinn (`inspector_maeve_quinn`) | Living innocent/discoverer |

The player detective is separate from all eight cards. Each of the seven living NPCs starts with a distinct private observation set, secrets, relationships, goals, suspicions, emotional state, beliefs, intentions, and runtime memory boundary.

## Admission and solvability validation

`validate_case` returned `valid=true` with zero issues. The generated-only admission pass verified:

- schema and ID/reference integrity;
- murder/timeline chronology, schedules, and participant co-location;
- physical evidence slot provenance and executable discovery routes;
- prerequisite closure and clue accessibility;
- character observation/knowledge provenance and distinct private agendas;
- means, motive, opportunity, and timeline support;
- non-red-herring reciprocal links to the solution;
- non-contradictory implication/exoneration and a uniquely best-supported culprit across independent evidence groups;
- at least two complete evidence routes with no shared evidence, prerequisites, or redundancy groups.

The accepted candidate is compiled into frozen Pydantic canonical models. NPC/provider output can select only finite semantic action or dialogue IDs and cannot patch canonical truth.

## Independent evidence routes

1. `lantern_documentary_route` — weapon, accounts, and stopped clock

   - Method: damaged poker (`acceptance_poker`)
   - Motive: restoration accounts (`acceptance_accounts`)
   - Opportunity: stopped mantel clock (`acceptance_clock`)
   - Timeline: `acceptance_timeline_a`

2. `lantern_trace_route` — transferred trace, demand, and return route

   - Method: metal trace (`acceptance_metal_trace`)
   - Motive: payment demand (`acceptance_demand`)
   - Opportunity: route note (`acceptance_route_note`)
   - Timeline: `acceptance_timeline_b`

Each route independently and uniquely implicates Gabriel Cross. Their evidence IDs, prerequisite closures, and redundancy groups are disjoint.

## Autonomous-NPC endurance trace

The API acceptance scenario completed six committed turns before following the proof route. All seven living agents resolved one action per turn: 42 normalized NPC action records. The deterministic semantic trace contained:

| Action kind | Count |
|---|---:|
| Move | 17 |
| Investigate | 13 |
| React to world event | 7 |
| Approach player | 2 |
| Private social exchange | 2 |
| Truthful player disclosure | 1 |

By turn six, living NPCs occupied six different rooms. Inspector Maeve Quinn had autonomously disclosed the stopped-clock observation; only its declared fact ID entered player knowledge. The turn-six storm event produced one reaction per survivor. The API dummy deliberately returned malformed planner responses after case generation, proving deterministic per-agent fallback through the same finite host action boundary. Separate contracts verify authorized misdirection, in-place investigation, approach, private information exchange, event reaction, evidence concealment, and the rule that murderer counterplay cannot eliminate the final complete route.

The case remained solvable. The player then reached the library and study through legal moves/searches and collected the complete documentary route. Autonomous activity never made that route inaccessible.

## Final accusation

The final report accused Gabriel Cross and selected the complete documentary route, `acceptance_timeline_a`, and host-confirmed contradiction `contradiction_1` between a host-owned denial bound to Cross's authorized clock-lie metadata and Maeve's stopped-clock observation. The provider's original murderer prose was never shown to the player.

| Dimension | Verdict |
|---|---|
| Culprit | Supported |
| Method | Supported |
| Motive | Supported |
| Timeline | Supported |
| Complete selected evidence route | Supported |
| Confirmed contradiction | Supported |

Evaluation score: **6/6**. The accusation solved the case.

## Replay, save, and audit

- Accepted player-action history: 14 entries, including free notebook contradiction marking.
- Resolved NPC action audit: 84 entries across the 12 committed investigation/final actions, including every affected actor, listener, and player knowledge delta.
- Debrief replay verification: `verified=true`; runtime and resolved action history reproduced from canonical truth plus action history.
- Generated v5 save: embeds canonical truth and fingerprint, revalidates on load, and requires no provider call. A separate golden v4 save emitted by the preserved foundation restores its historical positional NPC actions exactly and upgrades safely to v5.
- E2E save/load: the loaded public game view exactly matched the concluded view.
- Post-game audit includes canonical truth, both routes, the normalized NPC trace and knowledge deltas, final player knowledge, every NPC's private overlay/beliefs/intentions/memory, confirmed contradictions, and replay counts.

## Verification commands

Focused generated-case E2E:

```powershell
& 'C:\Users\dilan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import runpy,sys; sys.path.insert(0,r'C:\random scripting\game\backend\.venv\Lib\site-packages'); sys.path.insert(0,r'C:\random scripting\game\backend'); sys.argv=['pytest','backend/tests/test_procedural_end_to_end_acceptance.py','-q','-p','no:cacheprovider','--basetemp=pytest-e2e-final']; runpy.run_module('pytest',run_name='__main__')"
```

Result: `1 passed`.

Complete backend regression suite:

```powershell
& 'C:\Users\dilan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import runpy,sys; sys.path.insert(0,r'C:\random scripting\game\backend\.venv\Lib\site-packages'); sys.path.insert(0,r'C:\random scripting\game\backend'); sys.argv=['pytest','backend/tests','-q','-p','no:cacheprovider','--basetemp=.tmp-pytest-main-final-2']; runpy.run_module('pytest',run_name='__main__')"
```

Result: `325 passed`, with 18 existing FastAPI deprecation warnings.

Frontend contracts and production bundle:

```powershell
cd frontend
npm.cmd test
npm.cmd run build
```

Result: `16 passed`; Vite production build passed.

Windows distributable and real-artifact smoke test:

```powershell
$env:PYTHONPATH='C:\random scripting\game\backend\.venv\Lib\site-packages;C:\random scripting\game\backend'
& 'C:\Users\dilan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' build\build.py --skip-frontend
```

Result: 18.5 MB `dist/ai-murder-mystery.exe`; packaged smoke passed.

## Remaining limitations

- Real OpenRouter generation and real-model playtesting remain deliberately on hold; no credits were spent for this milestone.
- Ashwick Manor is currently the only location package. The interfaces validate arbitrary compatible packages, but location-content variety has not yet been demonstrated.
- The accepted candidate is a deterministic provider-shaped fixture used to test the production boundary; real-model rejection rate and prose quality are not yet measured.
- NPC autonomy is turn-based and finite-action, not continuous time. Counterplay is intentionally constrained by provenance and last-route solvability guards.
- The complete audit is exposed by the debrief API. The browser shows the player-facing verdict and solution, not every private audit field.
- Authored case/location IDs and legacy `ASHWICK_TRUST_DATA_DIR` storage identifiers remain unchanged for save and installation compatibility; Ashwick remains an in-world fixture name, not the product name.
