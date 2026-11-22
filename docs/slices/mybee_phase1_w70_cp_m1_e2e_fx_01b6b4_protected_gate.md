# CP-M1-E2E-FX-01B.6B.4 Replay, Restart, and ACK-Loss Protected Gate

## Status

- Date: `2026-11-18`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Migration: none; all four service migration inventories are applied by the protected matrix
- Actual databases: `nex_ae_test`, `nex_wc_test`, `nex_oa_test`, `nex_eos_test`
- Remote provider contacted: no
- Successor: `CP-M1-E2E-FX-01B.6B.5`

## Implemented Boundary

This Slice closes the installed persistence and replay Gate without adding a
new queue, recovery store, Product-specific worker, or financial authority.

1. The AE protected path migrates an isolated schema in the actual
   `nex_ae_test` database and uses the product SQLAlchemy repositories for
   Product Preparation checkpoints, generalized waits/events, runtime jobs,
   AgentPlan, PlanValidation, ExecutablePlan, and executable steps.
2. Both BUSINESS_FORMAL and ACCOUNTING_REVIEW waits survive reconstructed
   service objects and database engine disposal. Redelivered approval events,
   resume reconciliation, and coordinator ACK loss converge to the original
   checkpoint and RuntimeJob identities.
3. The durable `READY_FOR_D04` checkpoint is materialized through the admitted
   D12/D04 Product Capability Registry and scheduled only after the three plan
   artifacts are persisted. A second process composition returns exact replay
   and the original START_EXECUTION job.
4. Cross-tenant notification, unavailable fresh authority, stale event, and
   changed event semantics fail closed without changing row counts.
5. Existing owner-service protected tests prove WC multi-stage approval, OA
   Project authorization, EOS human approval evidence, VoucherCandidate
   revision/review/admission, and atomic journal replay on their actual test
   databases.
6. Exact replay leaves one proposal lineage, one candidate/review/admission
   lineage, one AgentPlan lineage, one executable plan, one START_EXECUTION
   job, and one posted journal. No duplicate financial or publication
   artifact is admitted.

## Productization Guard

- Business values used by the protected test are test-owned owner responses;
  no fixture or M1 value is introduced into product runtime source.
- Runtime persistence, matching, planning, and scheduling are the installed
  generic components. The test does not write internal tables in place of the
  product service after initial lineage seeding.
- Approval and accounting authority remain owner-service decisions. The Gate
  does not infer approval from event delivery or reuse approval evidence
  across domains.
- M1 remains globally `CONTRACT_ONLY`; worker activation is still assigned to
  `6B.5`.

## Verification

- focused 6B.1A through 6B.4 regression: `127 passed, 4 protected skips`
- focused 6B.4 runner and protected-test regression: `4 passed, 1 protected skip`
- actual four-database protected matrix: `8 passed`
- approval wait restart points: `2`
- approval ACK-loss redelivery: `PASS`
- exact proposal/candidate/review/admission/plan/job/journal replay: `PASS`
- cross-scope, unavailable authority, stale event, semantic drift: `PASS`
- negative-path zero mutation: `PASS`
- temporary-schema and owner-test zero residue: `PASS`
- remote provider required: `false`
- AE Slice Gate: `6659 passed, 51 skipped`; statement `96.44%`, branch `94.71%`
- AE product ownership coverage: statement `97.08%`, branch `95.01%`
- WC Slice Gate: `667 passed, 22 skipped`; statement `98.32%`, branch `96.23%`
- OA Slice Gate: `1244 passed, 14 skipped`; statement `96.65%`, branch `95.08%`
- EOS Slice Gate: `2297 passed, 67 skipped`; statement `97.00%`, branch `95.25%`
- contract, golden-journey transition, and demo/product dependency audits: `PASS`

Machine-readable evidence:

```text
reports/quality/mybee_phase1_w70_cp_m1_01b6b4_protected_gate.json
reports/quality/mybee-w70-cp-m1-01b6b4-ae-slice-gate.json
reports/quality/mybee-w70-cp-m1-01b6b4-wc-slice-gate.json
reports/quality/mybee-w70-cp-m1-01b6b4-oa-slice-gate.json
reports/quality/mybee-w70-cp-m1-01b6b4-eos-slice-gate.json
```

## Closure Decision

`CP-M1-E2E-FX-01B.6B.4` is implementation-closed. The installed persistence
chain now has actual PostgreSQL evidence for replay, restart, both approval
ACK-loss boundaries, deterministic plan scheduling, owner-service authority,
and zero residue. `6B.5` may activate the installed process composition
without introducing a Slice-local recovery mechanism.
