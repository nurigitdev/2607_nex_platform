# Slice 0581: AE supervised process operator-control boundary audit

## Scope

Start S59 by freezing the guarded operator-control boundary for AE supervised
scheduler daemon processes before broadening start, stop, or restart behavior.

## Decision

- AE remains the daemon process owner and persistence system of record.
- AG may provide an operator-facing dispatch surface, but it must call AE APIs.
- AG remains read-only over AE persistence and has no direct subprocess control.
- Operator control requires an operator subject, idempotency key, reason, and
  explicit approval for start/restart flows.
- The first runnable mode remains test-profile-only, explicit opt-in, bounded
  subprocess execution.
- `restart_daemon` is modeled as stop then start with distinct evidence rather
  than a magic in-place restart.
- Production continuous start remains disabled until later runtime policy work.

## Implementation

- Added
  `scripts/smoke/run_ae_supervised_process_operator_control_boundary_audit.py`.
- Added regression coverage for path checks, source-token checks, redaction,
  helper behavior, CLI summary output, and failure modes.
- Registered the audit in the default quality gate.

## Guardrails

- Slice 0581 does not start, stop, or restart a subprocess.
- Slice 0581 does not add a new database table or migration.
- Database URLs, service tokens, provider keys, local storage paths, raw daemon
  payloads, raw artifact payloads, and raw process snapshots are not emitted in
  audit evidence.
- PostgreSQL smoke remains a protected later step and must use the real test DB
  when enabled.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_supervised_process_operator_control_boundary_audit.py tests/test_ae_supervised_process_operator_control_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ae_supervised_process_operator_control_boundary_audit.py -q --cov=run_ae_supervised_process_operator_control_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ae_supervised_process_operator_control_boundary_audit.py --summary
```

## Next

- Slice 0582 should add the AE-owned operator-control policy contract/schema for
  action, operator subject, idempotency, reason, approval, and profile guards.
