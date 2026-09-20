# Slice 0874: AG concurrency admission and load shedding

## Goal

Prevent expensive AG audit-integrity work from consuming all database-pool
capacity during concurrent bursts.

## Implementation

- Added a process-local bounded concurrency admission guard.
- The guard consumes the validated S88 policy defaults: maximum eight in-flight
  operations, capped by configured API pool capacity, with a 100 ms wait.
- Applied the same guard to audit-integrity operations reads, evidence package
  creation, and package verification.
- Exhausted capacity fails fast with a retryable redacted `503` instead of
  waiting for a database-pool timeout.
- Lease release is guaranteed for normal returns and exceptions.
- Snapshot counters expose only capacity, in-flight, peak, admitted, and rejected
  counts. Operation names, payloads, credentials, and subject identifiers are
  not retained.

The guard is process-local. Multi-process deployment capacity remains the sum of
each worker's configured guard, and distributed quotas remain outside S88.

The lease uses an explicit context-manager object rather than a generator-based
context manager. This preserves existing frozen domain exceptions because the
lease never rewrites exception traceback attributes while releasing capacity.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_resilience_performance.py \
  tests/test_nex_ag_audit_evidence_operations.py \
  --cov=nex_ag.resilience_performance \
  --cov=nex_ag.audit_evidence_api \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
focused admission/API tests: 67 passed
resilience policy, audit operations, and audit API statement/branch: 100%
aggregate regression: 5959 passed, 1 known warning
statement=73085/73966=98.808912202904%
branch=17142/17792=96.346672661870%
```
