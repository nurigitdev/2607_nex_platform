# Slice 0594: AE operator-control execution API routes

## Scope

Expose protected AE API routes for the Slice 0593 metadata-only execution state
machine.

## Decision

- AE owns the execution route surface.
- The execution route accepts the same guarded operator intent shape used by
  the S59 preview route, builds the canonical facade internally, then creates a
  Slice 0592 execution request and Slice 0593 execution state.
- The default execution mode remains `contract_only`; callers must explicitly
  request `fake_dry_run_supervisor_persistent_dispatch` to receive an
  `ADMITTED` state.
- A separate transition route validates explicit state transitions such as
  `ADMITTED -> EXECUTING` without creating persisted dispatch evidence.
- Route catalog metadata now exposes the execution and transition endpoints.

## Implementation

- Added `POST /api/v1/artifact-retention/scheduler-daemon-operator-control-executions`.
- Added
  `POST /api/v1/artifact-retention/scheduler-daemon-operator-control-execution-transitions`.
- Refactored the existing preview route to share the same route-payload facade
  builder used by execution-state creation.
- Added route regression coverage for authentication, default contract-only
  blocking, explicit fake-dispatch admission, idempotency replay, transition
  evidence, invalid execution mode, invalid transition payloads, and scheduler
  config route catalog exposure.

## Guardrails

- Slice 0594 does not invoke the supervisor adapter.
- Slice 0594 does not persist execution state or transition rows.
- Slice 0594 does not write PostgreSQL rows, enqueue jobs, run workers, start
  subprocesses, stop subprocesses, or enable physical deletion.
- Database URLs, service tokens, local storage paths, raw artifact payloads, raw
  execution payloads, and raw supervised process snapshots remain excluded.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifacts.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_routes.py tests/test_nex_ae_artifacts.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_routes.py tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Next

- Slice 0595 should add protected PostgreSQL smoke evidence for the execution
  route using `NEX_AE_TEST_DATABASE_URL` while proving the metadata-only route
  leaves AE persistence unchanged.
