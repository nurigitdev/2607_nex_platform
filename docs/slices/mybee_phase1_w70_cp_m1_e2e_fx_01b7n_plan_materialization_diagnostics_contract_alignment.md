# CP-M1-E2E-FX-01B.7N: READY_FOR_D04 Plan Materialization Diagnostics and Contract Alignment

## Status

- Date: `2026-11-20`
- Status: `CLOSED / DOWNSTREAM EXECUTOR BLOCKER OPEN`
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Predecessor: `CP-M1-E2E-FX-01B.7M`
- Database migration: none
- Public API change: none
- Remote provider: required for final exact-head replay only

## Failure Reconciliation

The `.7M` exact-head journey completed separate business and accounting Human
approvals, produced accounting evidence and posting admission, and advanced the
Product checkpoint to `READY_FOR_D04`. The following Product resume job then
failed as `M1_PLAN_MATERIALIZATION_INVALID`.

That single code collapses WorkIntent, checkpoint integrity, OA/EOS authority,
capability snapshot, Project lineage, context quality, timestamp, UUID, and
plan-validation failures. The persisted RuntimeJob therefore proves that plan
materialization failed but cannot identify the violated contract.

## Decision

1. Preserve `M1_PLAN_MATERIALIZATION_INVALID` as the compatibility error
   family.
2. Persist a bounded typed reason as the RuntimeJob `error_ref`.
3. Separate WorkIntent, READY checkpoint, integrity, authority, reference,
   capability, identity, Project, execution, conflict, degradation, timestamp,
   and validation failures.
4. Do not persist prompts, provider output, credentials, or unrestricted error
   text in RuntimeJob diagnostics.
5. Re-run the exact-head installed journey after diagnostic admission and fix
   only the contract proven by the typed failure.
6. Do not weaken OA authorization, EOS accounting SoD, capability admission,
   or immutable checkpoint hashes.
7. Reuse current RuntimeJob and Product preparation persistence; add no table
   or migration.

## Diagnosed Contract Drift

The exact-head diagnostic replay persisted `M1_PLAN_IDENTITY_MISMATCH`. A
bounded read of the same execution proved:

- AgentExecution principal: `employee-8101`;
- AgentExecution requester: `employee-8101`;
- READY checkpoint requester subject: `employee-8101`;
- canonical AgentContext identity field: `principal_id=employee-8101`.

The materializer alone read the non-canonical field `identity.subject_id`.
Canonical AgentContext admission has always required `tenant_id`,
`principal_id`, `agent_id`, and `agent_type`, so this was field-name drift, not
an authority mismatch. The materializer now compares `principal_id` to the
authoritative requester subject. It does not add a legacy `subject_id`
fallback, because accepting an unvalidated identity shape would weaken the
planning authority boundary.

## Implementation

1. `M1_PLAN_MATERIALIZATION_INVALID` remains the compatibility error family,
   while the persisted RuntimeJob `error_ref` now carries a bounded typed
   materialization reason.
2. The materialization boundary distinguishes capability snapshot, validation,
   WorkIntent, READY checkpoint, preparation integrity, authority integrity,
   reference, capability set/drift, business context, identity, primary
   Project, execution, context conflict/degradation, UUID, and timestamp
   failures.
3. The identity contract now consumes the canonical AgentContext
   `identity.principal_id` and compares it with the authoritative READY
   checkpoint requester subject.
4. A legacy `subject_id`-only identity is rejected fail-closed. No fallback,
   fixture, public API change, or database migration was introduced.

## Verification

- Focused materialization and Product-router regression: `66 passed`.
- Focused M1 `01b*` regression: `534 passed`, `6 skipped`.
- Actual `nex_ae_test` PostgreSQL resume-settlement smoke: `2 passed`.
- AE Slice Gate: `PASS`; commands `6/6`; Python regression `6886 passed`,
  `53 skipped`.
- AE statement coverage: `96.46%`.
- AE branch coverage: `94.72%`.
- Exact-head source revision: `de6b281724100b5cf160ea807a17bce60d7fb9fc`.
- Canonical OCI release set: `9/9` artifacts, `9/9` non-root images, and
  `12/12` background/package checks passed.
- Product AE runtime image: `PASS`; NSL wheel `0.2.1`; runtime profile
  `VERIFIED_PRODUCT_RELEASE`.

## Exact-Head Live Result

The aligned installed replay used the actual eight PostgreSQL service
databases and the protected remote generation provider. Both Product resume
jobs reached `DONE`, and two executable plans were persisted. This proves that
the journey advanced through `READY_FOR_D04` plan materialization after the
identity contract correction.

The next failure occurred after materialization at executable step `E1`:

- capability: `PROJECT.WORK_CODE_SET.GET`;
- executor: `LOCAL_SKILL`;
- RuntimeJob error: `ae.p5_executor_callback_failed`;
- step `E1`: `FAILED`;
- dependent step `E2` (`FINANCE.VOUCHER.APPROVE_AND_POST`): `BLOCKED`.

This is a separate installed executor diagnostic/contract boundary. It is not
folded into this Slice. The recommended next corrective Slice is
`CP-M1-E2E-FX-01B.7O: Installed D12 LOCAL_SKILL Executor Diagnostics and
Contract Alignment`.

Cleanup verification found no running canonical containers and zero
`m1_01b7_%` schemas in `nex_ae_dev`.

## Exit Rule

The Slice closes only when focused regression and the AE Slice Gate pass, the
exact-head journey emits a typed materialization reason, the proven contract
misalignment is corrected without scenario fixtures, and the parent journey
advances beyond D04 plan materialization with zero residue.

All exit conditions are satisfied. `CP-M1-E2E-FX-01B.7N` is closed. Parent
Slice `.7` remains blocked at the downstream `LOCAL_SKILL` executor boundary.
