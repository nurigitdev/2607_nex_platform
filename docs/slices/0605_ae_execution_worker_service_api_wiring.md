# Slice 0605: AE execution worker service/API wiring

## Scope

Expose the Slice 0602-0604 operator-control execution worker flow through a
protected AE service route.

## Decision

- No new database table is introduced in Slice 0605.
- The route returns the existing worker result contract:
  `ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result.v1`.
- The worker route may consume either an inline execution state or an execution
  state id read from the existing
  `ae_daemon_operator_control_execution_states` table.
- Worker result persistence is still not introduced. Existing explicit
  execution state and transition persistence routes remain the only persistence
  path in this slice.

## Implementation

- Added protected
  `POST /api/v1/artifact-retention/scheduler-daemon-operator-control-execution-workers`.
- Advertised the route in the artifact retention scheduler route catalog.
- The route builds a worker plan and command, then invokes the fake dry-run
  worker with the configured fake supervisor adapter.
- Added regression coverage for authentication, inline state execution,
  persisted-state-id lookup, contract-only blocked execution, missing state
  input, missing store, missing row, and invalid state payloads.

## Guardrails

- The worker route still performs no database write, JobQueue enqueue,
  subprocess start/stop, supervisor result persistence, or physical deletion.
- Database use is read-only and only happens when the caller provides
  `operator_control_execution_state_id`.
- Future smoke evidence should combine this route with the existing explicit
  state/transition persistence flags against the AE test database.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifacts.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_routes.py
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_routes.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_routes.py -q --cov=nex_ae_api.artifacts --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

- Targeted regression: `18 passed`.
- Full regression/quality gate: `4251 passed`, exit code `0`.
- Coverage evidence: statement `98.56%`, branch `95.67%`.

## Next

- Slice 0606 should add protected PostgreSQL smoke evidence that persists an AE
  execution state in `nex_ae_test`, reads it through the worker route, records
  a transition, and cleans up the targeted rows.
