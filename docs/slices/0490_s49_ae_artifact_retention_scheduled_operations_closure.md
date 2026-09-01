# Slice 0490: S49 AE artifact retention scheduled operations closure

Close the S49 scheduled artifact retention operations thread with an automated
checkpoint.

## Changes

- Added
  `scripts/smoke/run_s49_ae_artifact_retention_scheduled_operations_closure.py`.
- The closure verifies Slice 0481-0489 evidence remains connected across AE
  boundary audit, schedule contract/schema, batch plan read-model/API,
  PostgreSQL smoke, scheduled command, mock worker, AG batch projection, and
  scheduled execution PostgreSQL smoke.
- Added regression coverage for pass/fail, missing files, token drift, CLI
  summary/JSON output, and missing-file text reads.
- Added the closure to the default quality gate in skip-safe form.

## Decisions

- AE remains the artifact retention system of record.
- AG keeps read-only operator projection semantics and does not write directly
  into AE artifact persistence.
- Scheduled execution stays dry-run by default; scheduler daemon startup,
  real background workers, and physical delete automation remain deferred.
- PostgreSQL evidence is protected by environment gates and must run against the
  AE test database profile when enabled.

## Evidence

```bash
./.venv/bin/pytest tests/test_s49_ae_artifact_retention_scheduled_operations_closure.py -q --cov=run_s49_ae_artifact_retention_scheduled_operations_closure --cov-branch --cov-report=term-missing
./.venv/bin/pytest
```
