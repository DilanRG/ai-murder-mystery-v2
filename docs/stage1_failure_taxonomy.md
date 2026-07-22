# Stage 1 Failure Taxonomy

Date: 2026-07-22
Scope: private Revision 9 and Revision 10 direct-DeepSeek qualification evidence
Sanitization: aggregate dispositions and validator messages only; no raw model responses, hidden case documents, or credentials are reproduced here.

## Preserved evidence

- Revision 9: commit `d466c683083195b3b3b9886d40afd792bcb95706`, six completed P2/P3/R1 cells, five Stage 1 passes, zero complete admissions.
- Revision 10: commit `682d4f38c3d2e6f674f6e22f26deb661f14b69c7`, six completed P2/P3/R1 cells, zero Stage 1 passes and zero complete admissions.
- Immutable ignored snapshots retain the journals, manifests, results, request metadata, and SHA-256 hashes for both revisions.

## Observed failure classes

| Class | Direct evidence | Contract diagnosis | Required correction |
|---|---|---|---|
| Oversized canonical output | Revision 10 Pro produced five `length` completions; all five became malformed or empty JSON. Revision 9 also recorded length-bound generation failures. | Stage 1 asks a reasoning model to author a large database-shaped document while reasoning inside the same output budget. | Request a compact semantic plan with a bounded output limit; let the host compile mechanical records. Treat `length`, empty, malformed, schema-invalid, semantic-invalid, and compilation failures separately. |
| Model-authored machine categories | Revision 9 had three Stage 1 schema rejections for categories such as `observation`, `discovery`, `physical`, `testimonial`, and `documentary`; Revision 10 had two more category/schema failures. | The model is being asked to remember internal enums that carry no narrative meaning. | The host assigns canonical categories from explicit semantic support-anchor roles. |
| Fixed method/weapon coupling | Repeated Revision 9 and 10 rejections reported that the generated method did not exactly match the selected fixed weapon or any hardcoded opportunity rule. | A global inventory and exact method string constrain the story arbitrarily and reject coherent novel means. | Let the model author a case-specific means concept and causal mechanism; the host creates its canonical object and validates provenance and access. |
| Universal culprit-victim co-location | Revision 9 and 10 rejected otherwise structured timelines because no culprit/victim co-location existed at the minute of death. | The rule conflates a direct attack with delayed poison, delivery, trap, or environmental mechanisms. | Validate a typed causal death chain. Require co-location only at a beat whose mechanism requires it. |
| Hidden support eligibility | Revision 9's five Stage 1 passes repeatedly failed Stage 2A for wrong categories, missing culprit linkage, missing event linkage, and absent method/motive/opportunity grounding. Revision 10 moved eligibility into a host catalogue, but three attempts still produced an empty catalogue and two lacked required axes. | Proof support was expected to emerge indirectly from generic facts rather than being an explicit Stage 1 responsibility. | Require method, motive, and opportunity/timeline semantic anchors that name semantic beats and explain culprit linkage. Compile these anchors deterministically into facts, events, and the support catalogue. |
| Survivor-map ownership confusion | Revision 9 rejected an incomplete survivor map; Revision 10 rejected a map containing all eight cards rather than exactly seven living NPCs. | The model must own narrative placement, but it was also responsible for exact canonical dictionary cardinality and victim filtering. | Require one proposed placement per living NPC using compact character references; validate exact coverage and let the host construct the canonical map. |
| Chronology and discovery inconsistencies | Captured failures included unsorted timelines, investigation before discovery, missing discovery ordering, and impossible room/access combinations. | Exact minutes and schema ordering obscured the semantic ordering requirement. | The model proposes relative beats and meaningful time windows; the host normalizes timestamps while preserving order, then validates access, continuity, death-before-discovery, and placement consistency. |
| Role drift risk | Earlier contracts let the model author victim and murderer fields inside a full replacement document. Repair regenerated whole stages. | Selected roles were neither engine-owned nor protected by a patch boundary. | Deterministically select and fingerprint `death_mode`, victim, responsible actor, and discoverer before generation. Reject acknowledgement mismatch and any repair touching locked roles. |
| Non-falsifiable repair | Revision 9 and 10 repair attempts were complete regenerations with textual rejection feedback. They did not preserve a parsed candidate, declare mutable paths, or prove that only defective fields changed. | A retry is not a repair and can silently replace correct upstream content. | Fingerprint the normalized candidate, return stable issue codes and paths, request a bounded delta, allow only declared paths, apply it locally, and rerun full validation. |

## Quantitative baseline

Revision 9 Stage 1 recorded five accepted stage outputs, one malformed response, three schema rejections, and six semantic rejections. All five accepted Stage 1 outputs later exhausted Stage 2A without producing a valid proof blueprint. Revision 10 recorded 18 Stage 1 requests: five malformed outputs, two schema-invalid outputs, and eleven semantic validator rejections. No Revision 10 cell reached Stage 2A.

The replacement contract is therefore not a relaxation of the validator. It moves mechanical authorship into deterministic host code while making the missing semantic obligations—causal mechanism, role acknowledgement, narrative placement, and support anchors—explicit and independently testable.
