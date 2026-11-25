# W80-CA00G.2 Amount-Tiered Policy Resolution and Approval-Line Selection

## Status

IMPLEMENTED / SLICE GATE PASSED

## Product Boundary

EOS now resolves an owner-scoped BusinessProposal revision into a deterministic
approval preview without adding another source of truth. Existing LegalEntity,
FX RateSnapshot, ApprovalPolicy, and OA candidate authorities remain canonical.

The service is scenario-neutral. It contains no tenant amount thresholds,
Project-count branches, fixed approvers, or M1 fixture values.

## Contract

- Only `DRAFT` or corrected `REJECTED` proposals can be previewed.
- Original proposal amount and currency remain immutable business input.
- Functional-currency thresholds use an admitted FX RateSnapshot; missing,
  malformed, or stale FX authority fails closed.
- Company-currency proposals use explicit identity normalization rather than a
  fabricated FX snapshot.
- Company, Project, and Project-set selectors reuse the existing EOS policy
  resolver. Every Project in a Project-set must resolve to the same policy hash.
- Required stages preserve the policy order and require one approver per stage.
- Candidates are accepted only from a fresh OA authority source, with inactive,
  duplicate, wrong-position, and requester-self candidates removed.
- Preview hashes bind proposal version/revision, content, normalized amount,
  policy, candidate evidence, and effective time.
- Approval-line hashes bind the exact selected subjects and OA authority hashes.
- Any revision, FX, policy, or OA candidate change invalidates stale selection.

No DB migration is needed for this resolution and selection boundary. Durable
submission binding remains the responsibility of W80-CA00G.3.

## Verification

- Focused branch-aware tests: `38 passed`; module coverage `98%`.
- ApprovalPolicy, approver resolution, FX, proposal persistence, and selection
  regression: `172 passed`, `3 skipped` by protected profile.
- Ruff check and format passed.
- NeX-EOS Slice Gate: `2377 passed`, `68 skipped`; statement `96.75%`, branch
  `94.76%`; contract, transition, dependency, and tiered checks passed.

No remote generation provider is required for this Slice.
