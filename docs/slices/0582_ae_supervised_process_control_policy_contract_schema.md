# Slice 0582: AE supervised process control policy contract/schema

## Scope

Add the AE-owned operator-control policy and request contract for supervised
scheduler daemon process control.

## Implementation

- Added operator-control policy schema/versioning in
  `nex_ae_api.artifact_retention_scheduler_daemon`.
- Added operator-control request schema/versioning for `status_probe`,
  `start_daemon`, `stop_daemon`, and `restart_daemon`.
- `restart_daemon` is represented as stop then start intent with distinct
  evidence requirements.
- Start/restart requests require operator subject, idempotency key, reason,
  test profile, enabled runtime, explicit opt-in, bounded max cycles, and
  granted approval by the same operator subject.
- Stop/status requests still require operator subject, idempotency key, reason,
  and test profile, but approval is optional metadata.
- Added regression coverage for normal policy/request paths, start/restart
  approval, stop approval metadata, validation errors, and redaction posture.

## Guardrails

- Slice 0582 is contract-only and does not expose a new route.
- Slice 0582 does not start, stop, or restart a subprocess.
- Slice 0582 does not create a new table or migration.
- AG remains a future dispatcher only; AE remains the process owner and
  persistence system of record.
- No database URLs, local storage paths, raw artifact payloads, raw execution
  payloads, raw process snapshots, provider keys, or service tokens are emitted.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_policy.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_policy.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
```

## Next

- Slice 0583 should add the pure admission decision state machine that consumes
  the request contract and current supervised process evidence.
