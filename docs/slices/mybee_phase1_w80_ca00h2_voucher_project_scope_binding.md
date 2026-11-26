# W80-CA00H.2 Voucher Project Scope Binding and Selection UX

## Status

IMPLEMENTED / SLICE GATE PASSED

## Product Boundary

- VoucherCandidate creation derives Project choices only from the approved
  proposal envelope projection.
- A single approved Project is automatically bound and displayed as a
  read-only `Project Code` field with its authority source explained.
- Multiple approved Projects require an explicit selection before draft
  creation; silent first-element selection is removed.
- A proposal without an approved Project Code remains visible for diagnosis
  but cannot create a VoucherCandidate.
- The UI exposes no arbitrary Project text field or tenant-specific fallback.
- EOS continues to revalidate tenant, company, active Project, and approved
  envelope membership at the protected create boundary.

## Implementation

- Reworked the voucher creation state around the selected proposal and its
  deduplicated approved Project set.
- Reset Project selection whenever proposal authority changes.
- Added automatic single-Project binding, explicit multi-Project selection,
  and bounded missing-Project diagnostics.
- Added focused React tests for automatic binding, explicit second-Project
  selection, and missing-Project fail-closed behavior.

## Verification

- Focused VoucherDraft React regression: `5 passed`.
- AE Web TypeScript check: passed.
- NeX-AE-Web Slice Gate: `297 passed`; statement `97.78%`, branch `97.28%`.
- Existing EOS out-of-envelope, inactive Project, revoked document, and
  lineage-mismatch zero-residue tests remain in the EOS ownership suite.
- Contract validation, transition audit, and demo/product dependency audit:
  passed.

Actual multi-service PostgreSQL and authenticated Playwright evidence remain
owned by `W80-CA00H.5`. No remote model provider is required for this Slice.
