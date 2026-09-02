# AG Scheduler Daemon Operations Runbook

## Purpose

Use this runbook when an operator needs to inspect AE artifact retention
scheduler daemon posture from AG, request a guarded manual tick-once, or collect
protected PostgreSQL smoke evidence. AE remains the system of record for daemon
config, lease state, JobQueue admission, artifact retention history, and all
runtime control decisions.

## Default Dashboard Checks

Run the metadata-only AG dashboard smoke first:

```bash
./.venv/bin/python scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py --summary
```

Expected default result:

```text
ag_artifact_retention_automation_operations_smoke=pass ... daemon_attention=READY ...
```

The AG dashboard is metadata-only. It should show
`daemon_manual_tick_once_available=true`, `daemon_start_daemon_available=false`,
`daemon_scheduler_daemon_started=false`, and `daemon_attention_status=READY`
when AE reports a safe manual tick-once path.

## Attention States

- `READY`: manual tick-once can be requested through AE API, while
  `start_daemon` and continuous loop execution stay policy-blocked.
- `LEASE_ATTENTION`: AE reports the scheduler lease repository is unavailable
  or cannot be used before a tick.
- `QUEUE_ATTENTION`: AE reports JobQueue admission is unavailable for retention
  scheduler jobs.
- `BATCH_WINDOW_ATTENTION`: AE blocks manual tick-once because the request is
  outside the configured retention batch window.
- `DISPATCH_ATTENTION`: AG is showing a latest dispatch snapshot that an
  operator should review before another manual request.
- `CONTROL_POLICY_BLOCKED`: AE blocks the requested control path by policy or
  admission configuration.

## Manual Tick-Once

Use AG only as the protected operator facade:

```bash
curl -s -X POST \
  http://127.0.0.1:8004/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once \
  -H "Authorization: Bearer <redacted AG token>" \
  -H "Idempotency-Key: <unique operator request key>" \
  -H "Content-Type: application/json" \
  -d '{"confirm_dispatch":true,"tenant_id":"tenant-slice-smoke","workspace_id":"workspace-slice-smoke","owner_user_id":"user-slice-smoke","run_worker":false}'
```

Set `confirm_worker_run=true` only when the operator intentionally wants AE to
run the worker path during a protected test. AG must never enqueue AE jobs or
write AE persistence directly.

## Protected PostgreSQL Smoke

The protected smoke is opt-in and must use `*_test` databases only. Configure
test database URLs and service tokens outside committed files:

```bash
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE=1
NEX_AE_TEST_DATABASE_URL=<redacted AE test database URL>
NEX_AG_AE_ARTIFACT_BASE_URL=<redacted AE API base URL>
NEX_AG_AE_ARTIFACT_SERVICE_TOKEN=<redacted AG to AE service token>
NEX_SERVICE_TOKEN=<redacted AG inbound service token>
./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py --summary
```

Expected protected result:

```text
ae_ag_artifact_retention_scheduler_daemon_postgres_smoke=pass ... live_db=true ...
```

Treat `skipped` as not executed. It is acceptable in the default quality gate,
but it is not live PostgreSQL evidence.

## Evidence Checklist

- Run `scripts/quality/run_quality_gate.sh` before committing a daemon
  operations slice.
- Capture `ag_artifact_retention_automation_operations_smoke=pass` for
  metadata-only dashboard evidence.
- Capture protected PostgreSQL smoke only when the test DB and AE/AG services
  are intentionally enabled.
- Confirm `start_daemon_allowed=false`, `continuous_loop_allowed=false`,
  `ag_direct_database_write_allowed=false`, and
  `ag_direct_job_enqueue_allowed=false` in AG operator guidance.
- Do not store raw service tokens, DB URLs, local storage paths, raw artifact
  payload, or raw execution payload in evidence files.
