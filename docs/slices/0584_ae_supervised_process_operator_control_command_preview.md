# Slice 0584: AE supervised process operator-control command preview

## Scope

Convert admitted operator-control requests into guarded supervisor command
previews without invoking a subprocess adapter.

## Implementation

- Added `ae_artifact_retention_scheduler_daemon_operator_control_command_preview.v1`.
- READY admissions produce validated supervisor command previews from the
  existing AE supervisor command contract.
- BLOCKED and NOOP admissions produce an empty preview list.
- `restart_daemon` preview decomposes to `stop_daemon` then `start_daemon`; the
  start command is marked as requiring follow-up admission after stop evidence.
- The preview carries only safe metadata, command envelopes, deterministic
  hashes, and redaction flags.
- Added regression coverage for status probe, start, blocked/noop, restart
  decomposition, validation drift, and redaction posture.

## Guardrails

- Slice 0584 is preview-only and does not expose a new route.
- Slice 0584 does not start, stop, or restart a subprocess.
- Slice 0584 does not invoke the supervisor adapter.
- Slice 0584 does not write to the database or enqueue the JobQueue.
- AG remains an operator-facing requester/observer only; AE owns all future
  command execution and persistence.
- No database URLs, local storage paths, raw artifact payloads, raw execution
  payloads, raw daemon runtime payloads, raw supervised process snapshots,
  provider keys, or service tokens are emitted.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_command_preview.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_command_preview.py -q
```

## Next

- Slice 0585 should add the AE service API facade for policy, admission, and
  command preview without executing process control.
