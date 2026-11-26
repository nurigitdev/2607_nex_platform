# W80-CA00G.5 Voucher Pre-Submission Review and Explicit Submit

## Status

IMPLEMENTED / PROTECTED POSTGRESQL ACCEPTED / CHECKPOINT PASSED

## Product Boundary

EOS remains the authoritative VoucherCandidate and revision source. AE adds an
owner-scoped browser facade, and AE Web adds the authenticated requester review
surface. Neither AE nor the browser stores another voucher aggregate.

This Slice does not add another accounting approval engine. Explicit submit
hands the reviewed candidate to the existing accounting review and approval
runtime. Product code contains no tenant-specific account mapping, fixed
Project, fixed debit/credit amount, or demo fixture fallback.

## Contract

- A requester can list and inspect only owner-scoped voucher candidates.
- `DRAFT` and `RETURNED` candidates can append an immutable review revision.
  Submitted, approved, posted, invalidated, and other terminal candidates are
  not editable.
- Every revision binds account, debit, credit, description, Project code,
  recognition date, source revision, and deterministic content hash.
- Validation checks balanced debit/credit totals, required Project attribution,
  recognition date, and current revision before submission.
- Submit is explicit. It binds the exact admitted revision and rejects stale,
  cross-owner, cross-tenant, malformed, or unbalanced requests fail closed.
- Exact replay returns the same candidate projection; semantic drift is not
  treated as replay.
- Canonical operation identities use
  `FINANCE.VOUCHER_PRE_SUBMISSION.{CREATE,LIST,GET,REVISE,VALIDATE,SUBMIT}`.
- Browser identity is derived from the authenticated AE session. Browser input
  cannot assert tenant or owner identity.

## Persistence and Admission

Migration `2552_eos_voucher_candidate_review_revision.sql` extends the existing
VoucherCandidate revision boundary with recognition-date evidence. It does not
introduce a second voucher header/line aggregate.

The EOS and AE OpenAPI contracts admit the new product surface. Because the EOS
contract digest changed, the existing W70 admission chain was regenerated with
the canonical builders: tool admission, D04/D12 manifests, immutable bundle
locks, product capability registry, platform compatibility lock, and foundation
receipt. The admitted EOS OpenAPI digest is
`e24527b8...b12b`; the AE OpenAPI digest is `6a2c60ef...3d3`.

## Verification

- Focused EOS and AE facade regression, rejection, replay, malformed-input, and
  owner-isolation branches passed.
- Actual `nex_eos_test` migration and isolated-schema PostgreSQL smoke passed;
  migration `2552` was applied and the smoke left zero residue.
- AE Web tests: `403 passed`; focused voucher tests: `6 passed`; TypeScript
  typecheck and production build passed. The existing bundle-size warning is
  unchanged and remains non-blocking.
- EOS Slice Gate: `2419 passed`, `69 skipped`; statement `96.36%`, branch
  `94.17%`, above the previous EOS branch baseline.
- AE Slice Gate: `7137 passed`, `55 skipped`; statement `96.42%`, branch
  `94.60%`.
- W70 admission, compatibility, and bundle regression: `186 passed`.
- Repository Checkpoint Gate: `23520 passed`, `196 skipped`; statement
  `98.12%`, branch `96.54%`; all `5/5` commands passed in `1747.032s`.
- Contract validation passed for `280` schemas, `322` examples, `260` negative
  examples, and `10` OpenAPI documents. Golden Journey transition and
  demo-to-product dependency audits passed.

No remote model provider is required for this Slice.
