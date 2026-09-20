# Slice 0902: CX SRS capability traceability inventory

## Goal

Map `CX-FR-001` through `CX-FR-008` to current implementation, contract,
migration, test, and route evidence before reassessing persistence gaps.

## Decision

- The inventory is machine-checkable and fails closed when an evidence file or
  required source token disappears.
- Every CX requirement must have all five evidence layers: implementation,
  contract, migration, test, and runtime route registration.
- `TRACEABLE` means the implementation has repository evidence. It is not a
  production-readiness or acceptance claim.
- Repository evidence is authoritative for the S91 re-audit; historical gap
  notes remain advisory inputs.
- This slice adds no database table or migration and mutates no CX data.

## Result

All eight requirements are traceable. The inventory provides the fixed input
for Slice 0903, which re-evaluates persistence gaps without relying on stale
descriptions.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_cx_capability_traceability_inventory.py --summary

./.venv/bin/pytest -q \
  tests/test_cx_capability_traceability_inventory.py \
  --cov=nex_cx.current_state_traceability \
  --cov=run_cx_capability_traceability_inventory \
  --cov-branch --cov-report=term-missing
```

Observed focused verification:

```text
inventory: PASS requirements=8 traceable=8 evidence=64 issues=0
focused tests: 5 passed
inventory module/runner statement and branch coverage: 100%
aggregate regression: 6287 passed, 1 known warning
statement=75725/76606=98.84995953319583%
branch=17660/18310=96.45002730748224%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
