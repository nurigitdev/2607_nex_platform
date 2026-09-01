# Slice 0509: AG Artifact Retention Automation Operations Projection

## Scope

Slice 0509 exposes AE artifact retention automation state through AG without
allowing AG to write AE persistence or enqueue AE jobs directly.

## Changes

- Added `ag_artifact_operation_retention_automation_projection.v1`.
- Added `GET /admin/v1/operations/artifact-retention/automation`.
- The projection combines AE batch-plan, scheduled-job, and retention-history
  read models into a single operator summary.
- The summary highlights dispatch availability, active/failed scheduled jobs,
  blocked execution history, operator-approval blockers, physical-delete
  automation status, and latest activity.
- Added a mock-first smoke script wired into the default quality gate:
  `scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py`.

## Guardrails

- AE remains the system of record.
- AG does not perform direct database writes.
- AG does not enqueue AE jobs directly.
- Physical delete automation remains disabled.
- Execute-mode physical deletion remains protected by operator approval.
- Projection and smoke evidence remain metadata-only and redacted.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py tests/test_ag_artifact_retention_automation_operations_smoke.py -q --cov=nex_ag.artifact_operations --cov=run_ag_artifact_retention_automation_operations_smoke --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py --summary
```

## Next

- Slice 0510 closes the S51 retention automation safety track.
