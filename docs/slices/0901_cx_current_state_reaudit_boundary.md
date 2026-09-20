# Slice 0901: CX current-state re-audit boundary

## Goal

Start S91 by freezing the NeX-CX current-state re-audit boundary before any new
CX feature or schema work begins.

## Decision

- The audit covers `CX-FR-001` through `CX-FR-008`: source registration,
  extraction, chunking, indexing, retrieval, context packages, grounded
  generation validation, and generation lineage.
- Repository code, migrations, contracts, and executable evidence are the
  primary facts. Earlier gap documents remain useful history but do not override
  later PostgreSQL write-through or runtime implementation.
- Existing CX modules are reused. Refactoring precedes feature work only where
  the audit proves stale coupling, duplicated responsibility, or an unsafe
  private-payload boundary.
- S91 requires an actual `nex_cx_test` re-audit before closure. Live provider
  evidence is supplementary because provider availability must not weaken
  deterministic regression.
- Slice 0901 adds no table or migration and does not mutate CX records.
- Object-storage activation, external vector-database selection, and production
  load/DR certification remain deferred.

## Slice Plan

1. Slice 0901: current-state boundary audit.
2. Slice 0902: SRS capability traceability inventory.
3. Slice 0903: persistence gap re-baseline.
4. Slice 0904: private payload/storage boundary decision.
5. Slice 0905: ownership and permission enforcement audit.
6. Slice 0906: runtime coupling/refactoring checkpoint.
7. Slice 0907: database and migration drift audit.
8. Slice 0908: contract and API drift audit.
9. Slice 0909: actual PostgreSQL re-audit and privacy runbook.
10. Slice 0910: S91 closure and S92 handoff.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_cx_current_state_reaudit_boundary.py --summary

./.venv/bin/pytest -q \
  tests/test_cx_current_state_reaudit_boundary.py \
  --cov=run_cx_current_state_reaudit_boundary \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
boundary audit: PASS scope=cx_fr_001_through_008 owner=nex-cx next=S92
focused tests: 5 passed
boundary runner statement/branch coverage: 100%
aggregate regression: 6282 passed, 1 known warning
statement=75664/76545=98.84904304657391%
branch=17656/18306=96.4492516114935%
```
