# Slice 0572: AE supervised process contract/schema

## Scope

Add the metadata-only supervised daemon process snapshot contract before any
real subprocess adapter is allowed to start or stop the AE artifact retention
scheduler daemon.

## Implementation

- Added
  `ae_artifact_retention_scheduler_daemon_supervised_process.v1`.
- Added builder, validator, summary, and summary-line helpers for supervised
  process snapshots.
- Bound snapshots to the existing AE supervisor command id, scheduler id,
  action, bounded max cycles, worker flag, output format, host id, optional
  process id, observed lifecycle status, timestamps, exit code, and termination
  signal.
- Added regression coverage for default missing status, guarded start request,
  running pid metadata, terminal stop/exit metadata, tamper detection, and
  lifecycle consistency failures.

## Guardrails

- Slice 0572 does not start or stop a subprocess.
- The default mode remains `bounded_loop_subprocess_test_only`.
- Production continuous start remains disabled.
- `start_daemon` snapshots require the same test-profile explicit-opt-in
  command contract introduced in S57.
- AG remains read-only and receives only safe metadata projections later.
- Snapshot payloads do not include database URLs, local storage paths, raw
  artifact payloads, raw execution payloads, provider secrets, or service
  tokens.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervised_process_contract.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_supervised_process_contract.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
```

## Next

- Slice 0573 should introduce the supervised process persistence boundary or
  adapter planning checkpoint while preserving the no-start guardrail until the
  subprocess adapter is explicitly wired and smoke-tested.
