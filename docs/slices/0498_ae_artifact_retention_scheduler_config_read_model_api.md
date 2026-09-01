# Slice 0498: AE artifact retention scheduler config/read-model API

Expose AE's scheduled artifact retention runtime posture through protected,
metadata-only API routes.

## Scope

- Added `ae_artifact_retention_scheduler_config.v1`.
- Added `ae_artifact_retention_scheduled_job_collection.v1`.
- Added protected AE routes:
  - `GET /api/v1/artifact-retention/scheduler-config`
  - `GET /api/v1/artifact-retention/scheduled-jobs`
  - `POST /api/v1/artifact-retention/scheduled-jobs/admission`
- Wired scheduled-job admission to the shared `JobQueue` through AE only.
- Added owner-scoped scheduled job filtering by tenant, workspace, owner, and
  common job status.
- Added top-level `trigger_type`, `command_summary`, and `job_summary` to the
  scheduled-job enqueue result so AG dispatch projections can stay metadata-only.

## Decisions

- AE remains the system of record for artifact retention scheduler runtime.
- AG may dispatch through AE's admission API, but AG still must not enqueue AE
  jobs or write to AE persistence directly.
- The scheduler daemon remains disabled; operator and scheduler-tick admission
  are available through AE API.
- Physical delete automation remains disabled.
- Scheduled job list responses validate the queued AE scheduled-retention job
  payload before returning it.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
