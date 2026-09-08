# Slice 0591: AE operator-control execution boundary audit

## Scope

Start S60 by freezing the protected execution boundary for AE supervised
scheduler daemon operator control.

## Decision

- AE remains the artifact, supervisor execution, daemon process, and persistence
  system of record.
- AG may keep an operator-facing dispatcher/projection, but it must call AE APIs
  and must not directly write AE persistence or signal subprocesses.
- Execution must consume the S59 validated policy/request/admission/command
  preview facade before invoking any supervisor adapter.
- The first executable mode is limited to the fake dry-run supervisor with
  persistent supervisor result/event evidence.
- Start/restart execution remains test-profile-only, approval guarded,
  explicitly opted in, and bounded by max cycles.
- Restart execution remains stop then start with distinct persisted results.
- Physical artifact deletion automation remains disabled from this
  operator-control surface.

## Implementation

- Added
  `scripts/smoke/run_ae_operator_control_execution_boundary_audit.py`.
- Added regression coverage for path checks, source-token checks, protected env
  redaction, helper behavior, CLI output, and failure modes.
- Registered the audit in the default quality gate.

## Guardrails

- Slice 0591 does not add a new execution route.
- Slice 0591 does not invoke a supervisor adapter.
- Slice 0591 does not write PostgreSQL rows or enqueue jobs.
- Database URLs, service tokens, provider keys, local storage paths, and raw
  daemon payloads are not emitted in audit evidence.
- PostgreSQL smoke remains a protected later step and must use the real test DB
  when enabled.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_operator_control_execution_boundary_audit.py tests/test_ae_operator_control_execution_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ae_operator_control_execution_boundary_audit.py -q --cov=run_ae_operator_control_execution_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ae_operator_control_execution_boundary_audit.py --summary
```

## Next

- Slice 0592 should add the AE-owned operator-control execution request/result
  contract/schema that consumes the S59 facade and produces metadata-only
  execution evidence.
