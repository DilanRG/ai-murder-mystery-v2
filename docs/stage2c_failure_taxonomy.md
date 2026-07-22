# Stage 2C Decomposition Failure Taxonomy

**Date:** 2026-07-23
**Scope:** Revision 15 decomposed Stage 2C qualification only.

This taxonomy preserves Revision 14 as the immutable baseline. Flash completed the old monolithic Stage 2C contract. Pro made three valid provider calls, but each exhausted the fixed 4,000-token completion allowance before returning a complete candidate. Those Pro attempts are output-budget failures, not semantic-validator rejections.

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

- Stage 2C-P owns suspect, seed, event meaning, apparent murder relevance, innocent explanation, intended channels, and distinctiveness.
- Stage 2C-R1 owns the first concrete suspicious trace and its independent resolution.
- Stage 2C-R2 owns the second realization and must bind the exact accepted R1 fingerprint.
- The host owns exact canonical structure and runs the complete Stage 2C, assembled Stage 2, and Stage-3-readiness validators.

A downstream delta may not compensate for an upstream defect. Changing P invalidates R1, R2, and assembly. Changing R1 invalidates R2 and assembly. No partial phase is a complete Stage 2 result.
