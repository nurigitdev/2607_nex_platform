# Slice 0583: AE supervised process operator-control admission state machine

## Scope

Add the pure AE-owned admission state machine that decides whether a validated
operator-control request may proceed to supervisor dispatch.

## Implementation

- Added `ae_artifact_retention_scheduler_daemon_operator_control_admission.v1`.
- Admission consumes the Slice 0582 operator-control request and optional
  current supervised process metadata.
- Current process input may be absent, a supervised process snapshot, a
  supervised process record carrying a snapshot, or a safe read-model style
  status object.
- Admission returns `READY`, `BLOCKED`, or `NOOP` with deterministic decision
  reasons and `next_supervisor_actions`.
- `restart_daemon` is admitted only for `RUNNING` or `STALE` process evidence
  and decomposes to `stop_daemon` then `start_daemon`; the start step requires
  follow-up admission after stop evidence.
- Added regression coverage for status probe, start/stop/restart state
  matrices, snapshot/record inputs, validation drift, current-process
  validation, and redaction posture.

## Guardrails

- Slice 0583 is admission-only and does not expose a new route.
- Slice 0583 does not start, stop, or restart a subprocess.
- Slice 0583 does not write to the database or enqueue the JobQueue.
- Supervisor dispatch remains a later AE-owned Slice.
- AG can later read or request through AE only; direct AG process control,
  database writes, and JobQueue enqueue remain blocked.
- No database URLs, local storage paths, raw artifact payloads, raw execution
  payloads, raw daemon runtime payloads, raw supervised process snapshots,
  provider keys, or service tokens are emitted.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_admission.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_admission.py -q
```

## Next

- Slice 0584 should convert admitted requests into guarded supervisor command
  previews without invoking a subprocess adapter.
