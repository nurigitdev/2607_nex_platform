# W80-CA00H.4 Voucher-Shaped Approval and NSL WRITE Projection

## Status

IMPLEMENTED / SLICE GATES PASSED

## Product Boundary

- EOS remains authoritative for the exact VoucherCandidate revision, Project
  Code, approved-document lineage, effective account name/code, debit/credit
  lines, totals, and balance.
- BUSINESS_FORMAL resolves its exact scoped approval case to the bound
  Candidate revision. NSL_WRITE carries only a typed, hash-bound Candidate
  selector in its display-safe summary; raw NSL payloads are never projected.
- AE adds an optional `ae_accounting_document_projection.v1` block without
  changing the existing `user_approval_projection.v1` line-item semantics.
- Missing, malformed, stale, cross-lineage, or unavailable accounting authority
  produces a bounded `UNAVAILABLE` diagnostic and never an inferred voucher.
- AE Web renders the authoritative voucher header, account names and codes,
  debit/credit lines, totals, balance, and collapsed lineage.
- No database migration, new business table, browser-owned account catalog, or
  scenario-specific fixture was introduced.

## Implementation

- Added the EOS accounting display service and protected internal case and
  Candidate endpoints, reusing scoped approval, accounting review,
  VoucherCandidate, and account repositories.
- Added signed AE-to-EOS display resolution to the approval facade and extended
  the browser contract with a strict optional accounting document block.
- Extended NSL approval publication with a validated display-safe Candidate
  reference derived by the active scenario-neutral controlled-skill runtime.
- Preserved the Golden A historical quarantine. An initial change to the
  hash-pinned `product_controlled_skill.py` was detected by the AE Gate, fully
  reverted to its frozen digest, and relocated to `controlled_skill_runtime.py`.
- Added focused service, protected API, facade, malformed-lineage, publication,
  React rendering, and unavailable-state tests.

## Verification

- Focused Python regression: `94 passed` across the new accounting projection,
  NSL publication, active-runtime ownership, and historical quarantine tests.
- Focused EOS protected API regression: `10 passed`.
- Focused AE Web approval regression: `14 passed`; TypeScript check passed.
- NeX-EOS Slice Gate: `2450 passed`, `69 skipped`; statement `96.34%`, branch
  `94.07%`; all 5 commands passed.
- NeX-AE-API Slice Gate: `7170 passed`, `57 skipped`; statement `96.34%`, branch
  `94.36%`; ownership audit passed with zero conflicts; all 6 commands passed.
- NeX-AE-Web Slice Gate: `297 passed`; statement `97.78%`, branch `97.28%`;
  all 5 commands passed.
- Contract validation, transition audit, Golden Journey audit, and
  demo/product dependency audit passed.

Actual AE/WC/OA/EOS PostgreSQL acceptance, authenticated Playwright evidence,
zero-residue checks, and the Repository Full Gate remain owned by
`W80-CA00H.5`. Remote model-provider access was not required for this Slice.
