# W80-CA00G.3 Proposal Product API and Review Workspace

## Status

IMPLEMENTED / PROTECTED POSTGRESQL ACCEPTED / CHECKPOINT PASSED

## Product Boundary

EOS remains the BusinessProposal source of truth. AE exposes an owner-scoped
browser facade and AE Web provides the authenticated proposal review surface.
No proposal state is duplicated in AE or the browser.

The product path is generic. It contains no tenant-specific thresholds, fixed
approvers, Project-count branches, or demo fixture values.

## Contract

- EOS exposes create, list, get, revise, approval-preview, approval-line
  selection, and submit operations under `/internal/v2/business-proposals`.
- AE derives tenant and requester identity from the signed user session and
  forwards commands to EOS with signed service trust.
- Browser-supplied tenant or owner identity is never authoritative.
- Proposal submission locks the exact revision, content hash, amount
  normalization evidence, approval policy, candidate evidence, and selected
  approval line.
- Exact replay returns the existing submitted aggregate. Owner, revision,
  content, policy, or approval-line drift fails closed.
- AE Web supports draft creation, immutable revision append, approval preview,
  required-stage approver selection, and explicit submission.
- Authentication-first routing and role-gated operations diagnostics remain
  unchanged.
- Static EOS and AE OpenAPI contracts admit the complete review surface and
  the MyBee compatibility lock pins their digests.

## Persistence

Migration `2550_eos_business_proposal_submission.sql` adds submission evidence
to the existing EOS aggregate. It does not introduce a second proposal table.
Inventory tests calculate the current migration head rather than freezing a
repository-wide count.

## Verification

- Focused EOS, AE, OA, and persistence tests: `99 passed`, one protected test
  skipped by default.
- Focused AE Web tests: `4 passed`.
- Actual `nex_eos_test` protected smoke: migration, submit, replay, stale
  binding rejection, and zero-residue checks passed (`21 passed`).
- Contract validation: `280` schemas, `322` examples, `260` negative examples,
  and `10` OpenAPI documents passed.
- Compatibility-lock and deployment-coupling audit: `9 passed`.
- OA Slice Gate: `1268 passed`, `14 skipped`; statement `96.39%`, branch
  `94.64%`.
- EOS Slice Gate: `2384 passed`, `68 skipped`; statement `96.46%`, branch
  `94.37%`.
- AE Slice Gate: `7133 passed`, `55 skipped`; statement `96.43%`, branch
  `94.62%`.
- AE Web Gate: `297 passed`; statement `97.78%`, branch `97.28%`.
- Repository Checkpoint Gate: `23483 passed`, `195 skipped`; statement
  `98.14%`, branch `96.58%`; contract validation, Golden Journey transition
  audit, and demo-to-product dependency audit passed.

No remote model provider is required for this Slice.
