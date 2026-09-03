# Slice 0539: AG Scheduler Daemon Runtime Attention Issue Candidates

## Scope

Make AG's scheduler daemon operations projection runtime-aware for operator
attention and issue candidate evidence. The slice uses AE's read-only runtime
observation from Slice 0538 and keeps all daemon runtime persistence and
execution authority in AE.

## Behavior

- `classify_artifact_retention_daemon_attention()` now accepts optional daemon
  runtime observation.
- Normal `BUSY` or `IDLE` heartbeat observations do not change the existing
  READY or latest-dispatch classifications.
- Runtime heartbeat-store unavailability is classified as
  `HEARTBEAT_ATTENTION` with operator actions to inspect the AE runtime route
  and configure the heartbeat store.
- Runtime heartbeat `ERROR` and observed-but-unknown heartbeat status are also
  classified as `HEARTBEAT_ATTENTION`.
- Daemon operations projection now includes metadata-only runtime
  `issue_candidates` with rule ids, severity, signal metadata, and recommended
  operator actions.
- Summary evidence includes `runtime_issue_candidate_count`.

## Guardrails

- Dispatch observations still take precedence so operators review the latest
  manual tick result before inferring daemon health.
- Runtime issue candidates do not include database URLs, storage paths, raw
  artifact payloads, execution payloads, or secrets.
- AG does not write heartbeat rows, scheduler leases, JobQueue records, or AE
  retention history.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE=1 \
  NEX_AE_TEST_DATABASE_URL=<redacted AE test database URL> \
  ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py --summary
```
