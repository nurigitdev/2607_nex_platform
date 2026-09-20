# Slice 0876: AG resilience and performance operations projection

## Goal

Expose the S88 runtime budgets and bounded operational counters without
revealing database URLs, credentials, SQL, raw exceptions, or source records.

## Implementation

- Added a protected `GET /admin/v1/operations/resilience-performance`
  projection for admin users and trusted service callers.
- Reports the shared API and worker SQLAlchemy pool capacity, checked-out,
  checked-in, overflow, available-capacity, and utilization metrics.
- Reuses the process-local admission and source-isolation instances so
  rejections, timeouts, failures, and slow operations are visible together.
- Distinguishes `READY`, `ATTENTION`, `NOT_CONFIGURED`, and `DEGRADED` states.
- Keeps this diagnostic read outside the admission gate so it remains
  available while normal AG work is saturated.
- Uses the existing persistence runtime and introduces no table or migration.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_resilience_performance_operations.py \
  tests/test_nex_ag_resilience_performance.py \
  tests/test_nex_ag_audit_evidence_operations.py \
  tests/test_nex_ag_audit_evidence_api.py \
  --cov=nex_ag.resilience_performance_operations \
  --cov=nex_ag.resilience_performance \
  --cov=nex_ag.audit_evidence_api \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
focused resilience-performance operations/API tests: 83 passed
resilience operations, policy, and audit API statement/branch: 100%
aggregate regression: 5975 passed, 1 known warning
statement=73237/74118=98.811354866564%
branch=17186/17836=96.355685131195%
```
