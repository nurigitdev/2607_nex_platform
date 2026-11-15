# W60-S7-03 Project P&L Authorization and Payroll Privacy

## Status

- Slice: `W60-S7-03`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Date: 2026-11-15
- Owners: NeX-OA, NeX-EOS, NeX-MyBee

## Decision

Project P&L reads now use the dedicated OA action `project:pnl:read`. Each
request requires a signed service token and fresh OA Project authorization
before request-shape or projection details are disclosed. The admitted query
shape is limited to one Project, one accounting period, and the latest
projection. Unknown filters and historical payroll-sensitive projection
selection fail closed.

Payroll privacy is enforced on aggregate evidence already produced by the
W60 labor bridge. No employee salary, person-level payroll, or individual
effort fields are added to the P&L contract. A payroll-sensitive projection is
denied when any contributing labor population is missing, suppressed, or
below its configured minimum population.

## Difference-Attack Guard

The new `eos_pnl_privacy_guard` table stores the first admitted semantic
fingerprint for a subject, Project, and accounting period. Exact replay is
allowed. A later request whose payroll component or population evidence would
produce a different fingerprint is denied, preventing repeated-query
subtraction across changing aggregate cells.

The guard is append-only at the PostgreSQL boundary. UPDATE and DELETE are
rejected by a database trigger. Public denials use the stable
`PAYROLL_PRIVACY_DENIED` response while internal reason codes retain the
operational distinction among missing evidence, small cells, suppressed
cells, historical selection, and fingerprint drift.

This Slice keeps the existing aggregate P&L response schema. Company and NVT
rollups remain outside this boundary and are reserved for S7-04.

## Implementation

- Added migration `2548_eos_pnl_privacy_guard.sql` with short constraint and
  index names, append-only protection, and migration registry evidence.
- Added in-memory and SQLAlchemy privacy repositories plus
  `EosProjectPnlPrivacyGuard`.
- Wired authorization-first admission into the EOS P&L API and query service.
- Added `project:pnl:read` to OA Project entitlement projection and lifecycle
  policy.
- Hardened the MyBee consumer to admit only aggregate-safe payroll component
  sources and reject person-level source references.
- Removed the historical S7-02C test's hardcoded global migration head. It now
  verifies ownership of migration `2545` against the current inventory.

## Verification

Focused regression and branch hardening:

```text
34 passed
pnl_privacy.py statement/branch coverage=100%
project_pnl_query.py statement/branch coverage=100%
```

Related EOS, OA, payroll, P&L, and MyBee regression:

```text
331 passed, 1 skipped
```

Protected PostgreSQL smoke against the actual test databases:

```text
nex_eos_test: 1 passed
nex_oa_test: 1 passed
isolated schemas removed with zero residue
```

Final NeX-EOS Slice Gate:

```text
2235 passed, 65 skipped
statement_coverage=97.02% (threshold 95.00%)
branch_coverage=95.30% (threshold 94.00%)
contract_validation=pass schemas=264 examples=315 negative_examples=257 openapi=10
golden_journey_transition_audit=pass
demo_product_dependency_audit=pass
tiered_quality_gate=pass commands=6/6
```

Evidence: `reports/quality/mybee_phase1_w60_s7_03_slice_gate.json`.

Remote model providers were not required. The pre-existing non-blocking
Starlette/httpx deprecation warning remains.
