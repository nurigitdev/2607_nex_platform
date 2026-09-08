# Slice 0587: AG operator-control facade projection

## Scope

Project the AE-owned scheduler daemon operator-control policy and preview facade
into AG as read-only operator metadata.

## Implementation

- Added AG projection schema version
  `ag_artifact_operation_retention_daemon_operator_control_projection.v1`.
- Extended the AG AE-artifact client protocol, in-memory client, and HTTP client
  with:
  - `scheduler-daemon-operator-control-policy`
  - `scheduler-daemon-operator-control-preview`
- Added protected AG admin routes:
  - `/admin/v1/operations/artifact-retention/scheduler-daemon-operator-control-policy`
  - `/admin/v1/operations/artifact-retention/scheduler-daemon-operator-control-preview`
- Added redacted projection helpers for policy, request, admission, command
  preview, current process metadata, supervisor preview metadata, source status,
  and summary rollup.
- Added regression coverage for projection redaction, route authorization,
  service filter validation, request validation, body/header idempotency
  precedence, in-memory facade states, and HTTP adapter request shape.

## Guardrails

- AG only displays and forwards operator-control intent through AE APIs.
- AG does not start, stop, restart, or signal AE subprocesses directly.
- AG does not write AE persistence, enqueue AE jobs, or invoke an AE supervisor
  adapter.
- Projection redacts idempotency keys, database URLs, storage paths, raw reasons,
  and private command bodies.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q
./scripts/quality/run_quality_gate.sh
```

Quality gate result: `3974 passed`, statement coverage `98.58%`, branch
coverage `95.79%`.

## Next

- Slice 0588 can fold the AG operator-control policy/preview surface into the AG
  operations dashboard while preserving AE process-control ownership.
