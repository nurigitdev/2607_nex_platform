# CP-M1-E2E-FX-01B.7M: Accounting Approval SoD Principal and Role Separation Alignment

## Status

- Date: `2026-11-20`
- Status: `IN PROGRESS`
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Database migration: none
- Product API change: none
- Remote provider: required only for the final exact-head installed replay

## Failure Reconciliation

The `.7L` installed journey proved Project Code authorization and delivered the
Project-scoped accounting approval decision to EOS. EOS then denied the
decision because the acceptance baseline used one Human principal as both the
sole business approver and the sole accounting approver.

That denial is correct. A person who prepares or submits a proposal or Voucher
must not approve the same business transaction, and the sole business approver
must not also be the sole accounting approver. Exceptional self-approval is not
an implicit fallback; it requires a separately governed policy and is outside
this Slice.

## Decision

1. Preserve the existing EOS separation-of-duties checks without weakening or
   bypassing them.
2. Use three distinct acceptance principals:
   - requester and Voucher preparer;
   - business approver;
   - accounting approver.
3. Target document signoff and ordinary controlled-write approval at the
   business `TEAM_LEAD`.
4. Target accounting posting approval at the finance `GROUP_LEAD`.
5. Grant `finance:journal:approve` only to the accounting approver. A leadership
   role alone never grants accounting authority.
6. Keep both approval principals as explicit Project members so OA publishes
   current Project Code authority; do not infer authority from tenant scope.
7. Drive each approval through a separate authenticated browser session and
   fail closed if no unique principal owns the pending gate.
8. Prohibit fixed case IDs, tenant dictionaries, identity fallback, and
   fixture-driven decision injection.

The two approval role names reuse the existing EOS leadership ladder. No new
organization or approval-role schema is introduced.

## Implementation

- The immutable acceptance baseline now declares distinct requester, business
  approver, and accounting approver identities.
- Baseline admission rejects missing, empty, or duplicate employee and subject
  identities.
- OA credentials and memberships are seeded independently:
  - business approver: `TEAM_LEAD`, approval read/decide, no journal approval;
  - accounting approver: `GROUP_LEAD`, approval read/decide and
    `finance:journal:approve`.
- EOS seeds separate business and finance organization positions and selects a
  different position type for `DOCUMENT_SIGNOFF` and `ACCOUNTING_POSTING`.
- Project membership and entitlement snapshots include all three principals.
- The Playwright acceptance harness opens three isolated browser contexts,
  polls both approval inboxes, routes the unique gate to its owning principal,
  records only bounded role categories, and verifies business/accounting actor
  separation.
- Post-restart result recovery remains requester-only and does not retain
  approval credentials.

## Verification

- focused M1 Python regression: `26 passed`.
- focused AE Web M1 harness: `15 passed`.
- full AE Web Node regression: `390 passed`.
- EOS accounting, document signoff, WC inbox, OA entitlement, and M1 regression:
  `266 passed`, `4 skipped` protected tests.
- actual PostgreSQL protected smoke: `4 passed`.
  - `nex_eos_test`: Human accounting SoD evidence and immutable decision;
  - `nex_eos_test`, `nex_wc_test`, `nex_oa_test`: document signoff replay and
    zero residue;
  - `nex_oa_test`: Project grant restart and authorization decision;
  - `nex_eos_test`, `nex_oa_test`: entitlement delivery replay and cleanup.
- AE Slice Gate: `PASS`.
  - tests: `6879 passed`, `53 skipped`;
  - statement coverage: `96.46%`;
  - branch coverage: `94.72%`;
  - commands: `6/6`;
  - active product coverage: statement `97.08%`, branch `95.02%`.

Exact-head installed live evidence remains pending.

## Exit Rule

The installed journey must show that:

1. requester, business approver, and accounting approver authenticate as three
   distinct principals;
2. business approval is completed only by the business approver;
3. accounting approval is completed only by the accounting approver;
4. EOS accepts fresh OA scope, Project Code, role, requester, preparer, and
   prior-business-approver separation;
5. Product execution advances beyond `WAITING_ACCOUNTING_APPROVAL` without an
   SoD denial;
6. replay/restart stays idempotent and all isolated database schemas are
   removed.

Any later failure is a separate typed boundary and must not re-collapse the
three principals or weaken EOS SoD.
