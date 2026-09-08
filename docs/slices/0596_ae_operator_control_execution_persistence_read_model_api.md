# Slice 0596: AE operator-control execution persistence/read-model API

## Scope

Add AE-owned persistence and read-model routes for artifact retention scheduler
daemon operator-control execution state evidence.

## Decision

- Execution state writes are explicit: the POST execution route persists only
  when `persist_execution_state=true`.
- Transition writes are explicit: the transition route persists only when
  `persist_transition=true`.
- Without those flags, the Slice 0594/0595 metadata-only route behavior remains
  unchanged.
- Read-model routes require an AE persistence store and return 503 when the
  store is not configured.
- AG remains a caller/projection surface only; AG must read this evidence
  through AE APIs and must not write AE tables directly.

## Implementation

- Added
  `SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore`.
- Added `0596_ae_operator_control_execution_persistence` migration for:
  - `ae_daemon_operator_control_execution_states`
  - `ae_daemon_operator_control_execution_transitions`
- The physical table names intentionally stay below PostgreSQL's 63-byte
  identifier limit so state and transition tables cannot collapse into the same
  truncated name.
- Added read-model builders for collection and detail responses.
- Added protected AE routes:
  - `GET /api/v1/artifact-retention/scheduler-daemon-operator-control-executions`
  - `GET /api/v1/artifact-retention/scheduler-daemon-operator-control-executions/{operator_control_execution_state_id}`
- Extended POST execution and transition routes with explicit persistence flags.

## Guardrails

- The new store records safe execution evidence only; it does not invoke a
  supervisor adapter, enqueue jobs, run workers, start/stop subprocesses, or
  enable physical deletion.
- Database URLs, passwords, provider API keys, local storage paths, raw artifact
  payloads, raw execution payloads, and raw supervised process snapshots remain
  excluded from route payloads and read-model evidence.
- Idempotency replay can be resolved from the persisted idempotency key only
  when `persist_execution_state=true`.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifacts.py services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_persistence.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_routes.py tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test ./.venv/bin/python scripts/db/run_migrations.py --service nex-ae-api --profile test
./scripts/quality/run_quality_gate.sh
```

Actual PostgreSQL route smoke:

```text
ae_operator_control_execution_postgres_route_smoke=pass collection_count=1 transition_count=1 deleted_states=1 deleted_transitions=1
```

## Next

- Slice 0597 should project this AE-owned execution read model into AG without
  giving AG direct database-write or process-control authority.
