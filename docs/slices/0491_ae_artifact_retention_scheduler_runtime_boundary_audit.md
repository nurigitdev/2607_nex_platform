# Slice 0491: AE artifact retention scheduler runtime boundary audit

Start S50 by freezing the runtime boundary for scheduled artifact retention jobs
before adding new JobQueue admission, worker adapters, or AG dispatch controls.

## Scope

- Added
  `scripts/smoke/run_ae_artifact_retention_scheduler_runtime_boundary_audit.py`.
- Added regression coverage for pass/fail evidence, redaction, CLI output,
  docs, and quality-gate wiring.
- Confirmed S50 starts from the closed S49 scheduled operations baseline.

## Decisions

- `nex-ae-api` remains the artifact retention system of record.
- S50 uses `common_job.v1` and the shared worker runner instead of introducing
  a standalone scheduler daemon.
- The first job type is `ae.artifact_retention.scheduled_execution`.
- Scheduled execution remains `DRY_RUN` by default and delegates to the existing
  guarded purge path through the Slice 0487 mock worker helper.
- Physical delete automation stays deferred beyond S50.
- `nex-ag` may read or dispatch through AE APIs, but must not write directly
  into AE artifact persistence.

## Planned Gaps

- Slice 0492: scheduled job contract/schema.
- Slice 0493: scheduled job planner and JobQueue admission.
- Slice 0494: scheduled worker runner adapter.
- Slice 0495: JobQueue/worker PostgreSQL smoke evidence.
- Slice 0496: AG scheduled job operations projection.
- Slice 0497: AG scheduled dispatch/control guardrail.
- Slice 0498: AE scheduler config/read-model API.
- Slice 0499: AE/AG scheduler PostgreSQL smoke evidence.
- Slice 0500: S50 closure checkpoint.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_runtime_boundary_audit.py -q --cov=run_ae_artifact_retention_scheduler_runtime_boundary_audit --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_runtime_boundary_audit.py --summary
```
