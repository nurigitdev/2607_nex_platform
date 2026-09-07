# Slice 0571: AE supervised daemon process activation boundary audit

## Scope

Start S58 by freezing the boundary for AE scheduler daemon supervised process
execution before enabling any real subprocess start path.

## Decision

- AE remains the artifact retention system of record, daemon process owner, and
  supervisor owner.
- AG remains read-only and metadata-only.
- The default supervised process mode remains disabled.
- The first real process mode is limited to bounded-loop subprocess execution
  under the `test` profile.
- Supervised `start_daemon` requires explicit opt-in, bounded max cycles, a
  process lock, PID metadata, a status probe, and later PostgreSQL smoke
  evidence.
- `stop_daemon` must be wired before any broader runtime enablement.

## Implementation

- Added
  `scripts/smoke/run_ae_supervised_daemon_process_boundary_audit.py`.
- Added regression tests for the boundary audit, protected environment
  redaction, missing files, missing source tokens, and CLI summary output.
- Registered the audit in the default quality gate.

## Guardrails

- Slice 0571 does not start a subprocess.
- Slice 0571 does not modify supervisor dispatch behavior.
- Production continuous start remains disabled.
- Database URLs, local storage paths, service tokens, provider keys, raw
  artifact payloads, raw execution payloads, and raw supervisor payloads are not
  emitted in audit evidence.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_supervised_daemon_process_boundary_audit.py tests/test_ae_supervised_daemon_process_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ae_supervised_daemon_process_boundary_audit.py -q --cov=run_ae_supervised_daemon_process_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ae_supervised_daemon_process_boundary_audit.py --summary
```

## Next

- Slice 0572 should add the metadata-only supervised process contract/schema
  before any subprocess adapter starts a process.
