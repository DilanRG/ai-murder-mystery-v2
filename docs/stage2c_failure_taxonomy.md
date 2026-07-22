# Stage 2C Decomposition Failure Taxonomy

**Date:** 2026-07-23
**Scope:** Revision 15 baseline and Revision 16 plan-item decomposition.

This taxonomy preserves Revision 14 as the immutable baseline. Flash completed the old monolithic Stage 2C contract. Pro made three valid provider calls, but each exhausted the fixed 4,000-token completion allowance before returning a complete candidate. Those Pro attempts are output-budget failures, not semantic-validator rejections.

## Revision 15 observed result

Revision 15 made eight measured semantic requests plus two exact-model preflights at exact commit `f723042780f77a5c85ccbb615d80791978f207cf`. Flash's first two combined-plan attempts stopped at the 2,600-token cap. Its third parsed but failed the unchanged semantic validator; one repair remained invalid and one was unauthorized. Pro's three combined-plan attempts all stopped at the same cap. Neither model reached R1 or R2. New estimated cost was USD 0.01158109, cumulative Stage 2 cost was USD 0.07213454, the ledger had zero open reservations, and Stage 3 request count was zero. The private result and ledger fingerprints are frozen in the Revision 16 manifest.

This is observed evidence that even the two-item planning response still couples too much high-reasoning work. Revision 16 therefore splits only P: P1 proposes one item with upstream bindings; P2 proposes only the second item and binds the exact accepted P1 fingerprint. The host assembles the existing two-item `Stage2CPlanCandidate` and runs its unchanged combined validator. R1, R2, the whole-Stage-2 validator, and the Stage-3-readiness gate remain unchanged.

## Baseline failure classes

| Class | Detection | Disposition |
|---|---|---|
| Provider or transport failure | Authentication, exact-model mismatch, provider error, timeout, or missing response accounting | Operational failure; never a model-quality rejection |
| Output-length stop | Provider finish reason is `length` | Count the attempt; do not patch a truncated document |
| Malformed or schema-invalid JSON | Parsing or Pydantic schema validation fails | Apply only the declared syntax policy; never infer missing semantics |
| Immutable-binding failure | Stage 2C-P changes a Stage 2A, Stage 2B, discovery-catalogue, or secondary-secret fingerprint | Reject the plan |
| Plan semantic failure | Non-innocent or duplicate suspects, unknown seed, true-route contamination, repeated suspicious channel, cosmetic duplicate, or unrealizable channel | Repair only plan-owned fields or reject Stage 2C-P |
| Realization binding failure | R1/R2 has the wrong plan index or fingerprint, or R2 lacks the exact accepted R1 fingerprint | Reject the realization; do not regenerate accepted upstream deltas |
| Realization semantic failure | Wrong affordance channel, self-resolving clue, rewritten innocent explanation, or R2 reuses an R1 discovery/resolution bottleneck | Repair only the defective realization |
| Host scheduling failure | Immutable actor timelines and room travel cannot fit the proposed secondary event | Reject the owning realization; the host does not rewrite Stage 1 |
| Combined Stage 2C failure | Host assembly differs from P/R1/R2, suspects duplicate, affordances overlap, provenance fails, or a red herring becomes true-route evidence | Reject the earliest defective Stage 2C substage |
| Whole Stage 2 failure | The unchanged evidence/solution validator or Stage-3-readiness gate rejects the assembled artifact | No admission and no Stage 3 request |
| Accounting or checkpoint failure | Open reservation, malformed ledger, missing source artifact, fingerprint mismatch, manifest mismatch, reordered checkpoint, or ambiguous interrupted request | Stop as an owner-visible safety blocker |

## Single-seed rule

Both accepted Stage 1 artifacts expose one secondary-secret seed. Stage 2C-P may reuse that causal seed for two materially different innocent secondary events, but it must select two different living innocent suspects and two different suspicious-evidence channels. The host includes both the seed owner and selected suspect in the secondary event, compiles a new Stage 2C fact naming those actual participants, and preserves the Stage 1 secret fact as a separate causal-seed link. It then assigns exact time, room, placement, actions, IDs, and provenance. This preserves Stage 1 while preventing false attribution and two cosmetic versions of the same red herring.

## Phase ownership and repair

- Stage 2C-P1 owns the first item's suspect, seed, event meaning, apparent murder relevance, innocent explanation, intended channels, and distinctiveness.
- Stage 2C-P2 owns the same fields for the second item, binds exact P1, and must satisfy the pairwise independence rules. It cannot restate P1 or upstream fingerprints.
- Stage 2C-R1 owns the first concrete suspicious trace and its independent resolution.
- Stage 2C-R2 owns the second realization and must bind the exact accepted R1 fingerprint.
- The host owns exact canonical structure and runs the complete Stage 2C, assembled Stage 2, and Stage-3-readiness validators.

A downstream delta may not compensate for an upstream defect. Changing P1 invalidates P2, R1, R2, and assembly; changing P2 invalidates R1, R2, and assembly. Changing R1 invalidates R2 and assembly. No partial phase is a complete Stage 2 result.
