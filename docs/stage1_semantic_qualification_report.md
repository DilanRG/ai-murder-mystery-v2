# Stage 1 Semantic-Compiler Qualification Report

**Date:** 2026-07-22

**Branch:** `stage1-semantic-compiler`

**Revision 10 baseline:** `682d4f38c3d2e6f674f6e22f26deb661f14b69c7`

**Exact qualification commit:** `bbf7d1f46cfc138f442c298e0a57ead0a7bacab4`

**Disposition:** Passed for both direct DeepSeek models; stopped before Stage 2 as required.

## Contract delivered

The engine deterministically selects and locks the homicide victim, responsible actor, and discoverer from the chosen eight cards and seed. The provider sees aliases and acknowledges those fixed roles but cannot choose or repair them. The frozen qualification stores only the role-assignment fingerprint in tracked material.

The model authors motive, causal rationale, a case-specific means and its provenance/mechanism, ordered causal beats, proposed rooms and time windows, access/opportunity, cover behaviour, discovery, survivor placements, support anchors, and required relationship/secondary-secret seeds.

The host assigns canonical IDs and internal enums, normalizes exact timestamps, maps aliases, creates the case-specific means record, builds fact/event links and the survivor map, derives the proof-support catalogue, and fingerprints the normalized plan and compiled Stage 1. It rejects missing semantic meaning instead of inventing it.

Validation now follows the complete causal chain. Direct attacks require responsible-actor/victim co-location at the attack event; delayed mechanisms may bind the responsible actor to an earlier preparation or delivery event instead. A provider-free suicide-compatible representation test passes, while production New Story and runtime support remain homicide-only.

Parsed semantic failures use fingerprint-bound replace-only deltas over issue-authorized paths. Locked-role changes, stale fingerprints, and unauthorized paths fail closed. Malformed complete JSON and length-truncated output are classified separately; truncation is never patched.

## Frozen input and controls

- Manifest: `backend/experiments/stage1_semantic_qualification_manifest.json`
- Manifest fingerprint: `320b2aa358654fa697c6b4e1a911994cbc40ecd12737966364e42ca95c297220`
- Location: the Ashwick Manor in-world fixture
- Cast: one frozen eight-card cast
- Seed: `2026072201`
- Role fingerprint: `9c5dde08e244654c086422b0f14cf8b76acb469c9d1d83b38303129cf0761616`
- Transport: direct DeepSeek, no provider/model fallback
- Order: Flash, then Pro
- Plan output cap: 6,000 tokens
- Initial plan attempts: at most three per model
- Semantic delta repairs: at most two per parsed candidate
- Repair reasoning: disabled; semantic-plan reasoning: high
- Fresh budget: USD 10.00; USD 8.50 soft stop; USD 9.50 operational stop; USD 0.50 reserve
- Stop boundary: valid compiled Stage 1 plus proof-support catalogue; zero Stage 2 requests

The optional free OpenRouter smoke was skipped because it was not necessary for qualification and was not cleanly verifiable without involving separate routing/privacy conditions.

## Qualification evidence

- Backend: 437 tests passed.
- Frontend: 16 tests passed.
- Production Vite build: passed.
- Windows PyInstaller build: passed; 18.2 MB executable.
- Packaged executable smoke: passed.
- Static syntax and `git diff --check`: passed.
- Disclosed development API key prefixes: absent from tracked project paths.

The falsifiable Stage 1 suite covers deterministic roles, role drift, missing actors/events/support axes, invalid survivor maps, impossible travel, delayed-death validity, direct-attack co-location, suicide-compatible representation, malformed/empty/truncated/schema-invalid responses, stale fingerprints, unauthorized repairs, and a genuinely applied semantic delta.

## Provider requests

DeepSeek did not expose a billed USD field. Costs below are local estimates from returned token/cache meters and the configured price card; they are not provider-dashboard billing observations. All six responses reported the exact requested model and no fallback.

| Model | Request/task | Result | Finish | Prompt (cached/miss) | Completion (reasoning) | Latency | Estimated USD |
|---|---|---|---|---:|---:|---:|---:|
| Flash | `052e3186935e4138b53267020a07d616` plan 1 | Semantic reject: responsible chain disconnected; discovery not downstream of death | stop | 7,075 (0/7,075) | 4,581 (3,012) | 36.605 s | 0.00227318 |
| Flash | `4c2aadb725464b95aace34592cf57ee8` delta 1 | Rejected: unauthorized patch path | stop | 1,712 (0/1,712) | 704 (604) | 6.189 s | 0.00043680 |
| Flash | `d498746b10164326816cb62098bfeadb` delta 2 | Admitted Stage 1 | stop | 1,712 (1,664/48) | 1,394 (626) | 10.379 s | 0.00040170 |
| Pro | `c428942986e44a36be0b9298b36ba10e` plan 1 | Rejected: truncated; no patch attempted | length | 7,075 (0/7,075) | 6,000 (4,665) | 90.609 s | 0.00829763 |
| Pro | `e64f1b4649c74a999a129e2a47e896dd` plan 2 | Rejected: truncated; no patch attempted | length | 7,075 (7,040/35) | 6,000 (4,545) | 88.948 s | 0.00526075 |
| Pro | `fa9b1a4bbe914d7a852f041e09d0a2ee` plan 3 | Admitted Stage 1 | stop | 7,075 (7,040/35) | 5,563 (3,837) | 83.856 s | 0.00488056 |

Flash used 10,499 prompt tokens, including 1,664 cached tokens, and 6,679 completion tokens, including 4,242 reasoning tokens. Its total latency was 53.173 seconds and its locally estimated cost was USD 0.00311168.

Pro used 21,225 prompt tokens, including 14,080 cached tokens, and 17,563 completion tokens, including 13,047 reasoning tokens. Its total latency was 263.413 seconds and its locally estimated cost was USD 0.01843894.

The combined locally estimated cost was **USD 0.02155062**, with zero open reservations and USD 7.97844938 remaining before the soft stop. Provider-dashboard reconciliation was unavailable at report time.

## Outcomes

Flash passed from its first parsed plan after two bounded deltas. Its first delta tried to modify an unauthorized path and was rejected; the second stayed within the declared repair scope and passed complete semantic validation, host compilation, compiled-core validation, and proof-support catalogue validation.

Pro's first two plan attempts exhausted the 6,000-token output cap and were classified as truncation. Neither was parsed, patched, or reinterpreted as success. Its third attempt completed and passed without repair.

Accepted fingerprints:

| Model | Semantic plan | Compiled Stage 1 | Proof-support catalogue |
|---|---|---|---|
| Flash | `5428e613bfbbaed4c149843f913d5007a3e59914c02a65de034fb3ae186dbbf4` | `f3dfdf8eb50f06c5ff5dc267141f2aaf2ca8b50c92f02ad5ddec7ec659c11166` | `2727a28b41880a54ff0a1b93b96fc04f08c4d7da0cd9af2bce569ab8bfc7a85c` |
| Pro | `87d90da4b06ad0eea1b2cc987445134e6eb241c6ea6d91bb4fe779395ab66814` | `642f86e0ffd8a60a5ee372727ecdb6788432765df45dac74d46e2ea0334b26fd` | `d3ed314b09e9769b7af26ee5f85dd017257b99f18b4a586f0e605557630081da` |

Both accepted outputs are valid inputs to the existing Stage 2 boundary. Accepted semantic plans and compiled truth remain only in the ignored private artifact area. No Stage 2 generation, full-case admission, NPC initialization, or playtesting occurred.

## Limitations and next milestone

This is one cast, one location, one seed, and one result per model. It establishes contract viability, not comparative narrative quality or a reliable production success rate. Flash needed semantic repair, while Pro needed all three initial attempts and showed significant output-cap pressure. The current qualification does not justify a general model preference.

The next recommended milestone is a separately authorized Stage 2 compatibility evaluation: feed both exact accepted Stage 1 artifacts into the unchanged Stage 2A proof blueprint, 2B evidence realization/provenance, and 2C misdirection/connective pipeline; run the unchanged whole-case validator; compare rejection concentration and cost without regenerating valid Stage 1. That milestone must remain separate from this report's successful Stage 1 boundary.
