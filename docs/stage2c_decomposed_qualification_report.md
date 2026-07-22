# Decomposed Stage 2C Qualification Report

**Date:** 2026-07-23  
**Status:** Passed for direct DeepSeek Flash and Pro; stopped at the Stage 3 owner-review gate.  
**Exact qualification commit:** `fb8052f87bef5eb4df0f02c10647ff2d599ef7ea`  
**Manifest fingerprint:** `f13ef11e64f9a499e603ad6de6b099afd336da0f2b914f5dabed241883589719`

## Outcome

Revision 19 completed the owner-authorized decomposed Stage 2C qualification. Exact direct `deepseek-v4-flash` and `deepseek-v4-pro` calls independently accepted P2, the host-assembled two-item plan, R1, R2, compiled Stage 2C, the unchanged assembled Stage 2 evidence/solution gate, and Stage-3-readiness. Every current semantic provider stage passed on its first initial attempt. No syntax repair, semantic delta repair, fallback, model substitution, provider failover, manual candidate edit, or Stage 3 provider request occurred.

This is a Stage 2 contract qualification over two different accepted Stage 1 stories. It is not a controlled model-quality comparison, a production-case admission, or a Stage 3/NPC-runtime evaluation.

## Exact reused provenance

| Boundary | Flash | Pro |
|---|---|---|
| Stage 1 semantic plan | `5428e613bfbbaed4c149843f913d5007a3e59914c02a65de034fb3ae186dbbf4` | `87d90da4b06ad0eea1b2cc987445134e6eb241c6ea6d91bb4fe779395ab66814` |
| Compiled Stage 1 | `f3dfdf8eb50f06c5ff5dc267141f2aaf2ca8b50c92f02ad5ddec7ec659c11166` | `642f86e0ffd8a60a5ee372727ecdb6788432765df45dac74d46e2ea0334b26fd` |
| Proof-support catalogue | `2727a28b41880a54ff0a1b93b96fc04f08c4d7da0cd9af2bce569ab8bfc7a85c` | `d3ed314b09e9769b7af26ee5f85dd017257b99f18b4a586f0e605557630081da` |
| Compiled Stage 2A | `40b6c23b2af535f4f0e8e115477d747a931c1d9fd600146734012692ccf499d3` | `7fe0015aa956086ffbf7377cb93bd9976efa917f673ba9544f9fe9b4128dfa76` |
| Compiled Stage 2B | `c480ce74c4c1d739a22a3a7339bcdd2b781d5edbf6fc1ace858402582bd87b3f` | `74ca4dcde3484d1fe6280b4ecb82eabbe4bcf08cf4034de81fad21af03a0e2ae` |
| Accepted Revision 16 P1 | `fc318565ab97764ae80b85ad327244e1182b87564c772161c7b1ffbf7d552c20` | `cbb888f576f4477b97f5257cac43cc26bb047d73541ea8b120985fc2defe0e00` |

The controller byte-verified the preserved Revision 15–18 result, ledger, request, attempt, checkpoint, and accepted-artifact evidence before starting the new ledger. Revision 19 regenerated neither Stage 1 nor the accepted Stage 2A/2B/P1 prefix.

## Accepted Revision 19 artifacts

| Result | Flash | Pro |
|---|---|---|
| P2 | `4e1f2f8cf400e9d60baee5ff7e0867db94eb1f63f75005cca9c2ce2c3a56bfbe` | `d1d3898aeb8e157fbc68b1da7554a2a5a09b90e84de635b7c8fef74b2a1f1145` |
| Assembled plan | `e251506614298ed04fae9d1ae3d928dc366cb801bac7413a352663a7e0efe9e9` | `d73bb45bbb84fca234c87e65dbb23f6810bbca700f3772faedc4a43ff9effc83` |
| R1 | `ec040e1f57457f52f25a011c78054ff0449bf579eb34acfae56085ca40dbf981` | `486a710788f9b395d1dfc89a07ddc5c1b6f687540142cf26c8a28d269e779442` |
| R2 | `fcce39d4a154d37224a478113e19387e64e9a12c7d9fdf0a024b0b6dcccc1e48` | `7a28f4c274f0aab5ddaa48120b7e4fa03e2aa52ea3d9c81b4742e2f3789772c3` |
| Compiled Stage 2C | `0d2aef33ce16699174887412d19cb08bd41645f7dae088607c64d3b206ca661f` | `30cf242d7d57bd377f8326fed7b121c2a6de262b3cd5c67c44fcdca68c17d5a2` |
| Accepted Stage 2 artifact | `f9a91ac616f1cb448f71e307f713618ebe88424b17215356264d107c271139fb` | `af32dad0d4a5aa4011fef387589d5b8433cee68fb90531c55d6b9ba5253be239` |
| Red herrings / distinct suspects | 2 / 2 | 2 / 2 |
| Stage-3-readiness | passed | passed |

## Provider evidence and accounting

Both exact-model preflights returned the requested model. Every semantic request finished with `stop`; none stopped for length. Cache-token, latency, and retry fields were unavailable from this direct endpoint and are recorded as unavailable rather than inferred.

| Model / stage | Request ID | Prompt | Completion | Reasoning | Local settled estimate |
|---|---|---:|---:|---:|---:|
| Flash preflight | `b6cda62e47134753b7fae2164622e094` | 10 | 1 | 0 | $0.00000168 |
| Flash P2 | `91bdaae2d0d747dda147cee899ef6edb` | 1,517 | 1,961 | 1,683 | $0.00065610 |
| Flash R1 | `7f3762d8825e4646b044b62cc5624d66` | 2,835 | 280 | 0 | $0.00047530 |
| Flash R2 | `66436872d73146ba92079dcbbf5b2ff3` | 2,988 | 325 | 0 | $0.00050932 |
| Pro preflight | `98fd6007021547ddb769b83822182209` | 10 | 1 | 0 | $0.00000522 |
| Pro P2 | `81350742b629430ba46b5cdb9566f28d` | 1,594 | 3,053 | 2,747 | $0.00301821 |
| Pro R1 | `4e4a2f9cf67f45828cff66ed24e0f698` | 2,914 | 405 | 0 | $0.00161994 |
| Pro R2 | `8bfd124e82ad4e57821a4f2888886e2a` | 3,047 | 388 | 0 | $0.00166301 |

- New Revision 19 locally settled estimated cost: **$0.00794878**.
- Cumulative Stage 2 locally settled estimate: **$0.11792935**.
- Provider-billed cost field: unavailable; the local values are estimates from measured token usage and configured direct-DeepSeek pricing.
- Open reservations at completion: **0**.
- Stage 3 provider requests: **0**.

## Immutable private evidence

| Artifact | SHA-256 |
|---|---|
| `qualification_results.json` | `2ff8a24c1f0e3f3c358d7f229ea7fad68f9c5185c58a9ed672d9f941ad3aaa10` |
| `cost_ledger.jsonl` | `b36d978723f157cd0f3de1c9b60c67cc8135ed45320d1998c6764cb79971fe1c` |
| `requests.jsonl` | `cdd1aa1fdfb6c0b8fded7cf50024c87ce96340af5588744ce5f6f49a1ff7547d` |
| `attempts.jsonl` | `a0091d2ca6143f8908e3cc96db108babcc12699a6585cfa2d3288ec98778997c` |
| Flash checkpoint | `e6f1f4b3e6ef42a5edb675c4d6debb1e365186d910001b29be1e55e374c426b7` |
| Pro checkpoint | `c200c8e0f5bfcce91b450757d70cef7343e7f5e0af7c37aedc75aeeeb7a1bec7` |
| Flash accepted document | `a7d74210bb5686d19a01327a8c1bf75459444d7c408505d0c0bc0317563d8f8f` |
| Pro accepted document | `db04003de8fdee5f1b848d43e8945313925a1e38bb8b2762dbc2b34e8913f8ff` |

Private candidate truth remains ignored and is not committed. These hashes provide tracked audit anchors without publishing hidden case material.

## Qualification gate

- Focused Stage 2/Stage 2C controller tests: 95 passed.
- Complete backend suite: 545 passed.
- Frontend tests: 16 passed.
- Production Vite build: passed.
- Windows PyInstaller package: passed, 18.2 MB.
- Packaged executable live HTTP smoke: passed.
- `git diff --check`: passed.
- Independent read-only P0/P1/P2 audit: passed after its observed alias-safety findings were fixed and regression-tested.

## Decision

The decomposed Stage 2C contract is qualified for both direct DeepSeek models over their exact accepted inputs. Stage 2 now has a complete fingerprinted candidate artifact and a passing Stage-3-readiness result for Flash and Pro. Per the Goal boundary, work stops here for owner review. Stage 3 provider generation, NPC initialization, full-case production admission, and playtesting remain explicitly out of scope for this qualification.
