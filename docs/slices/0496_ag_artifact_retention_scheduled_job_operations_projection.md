# Slice 0496: AG artifact retention scheduled job operations projection

Add an AG read-only projection for AE artifact retention scheduled jobs without
letting AG enqueue, mutate, or inspect AE persistence directly.

## Scope

- Added `/admin/v1/operations/artifact-retention/scheduled-jobs`.
- Added the `ag_artifact_operation_retention_scheduled_job_projection.v1`
  projection contract.
- Extended the AG AE-artifact client protocol, in-memory client, and HTTP client
  to read `/api/v1/artifact-retention/scheduled-jobs`.
- Projected scheduled job metadata, common job status, safe AE route links,
  command summary, retry indicators, and estimated deletion counts.
- Added regression coverage for projection summary/redaction, sparse payloads,
  in-memory filtering, route auth/filter failures, source failures, HTTP request
  shape, and main app route registration.

## Decisions

- AE remains the system of record for scheduled retention jobs and the shared
  JobQueue rows behind them.
- AG exposes a metadata-only operator read model; it must not write to AE
  persistence or enqueue AE retention jobs directly.
- Nested scheduled command payloads are intentionally not projected. Operators
  receive command identifiers and summaries, while AE keeps the source payload.
- PostgreSQL evidence is deferred to the AE/AG integration smoke slice because
  the AE scheduled-jobs source route is still a future endpoint.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
scripts/quality/run_quality_gate.sh
```
