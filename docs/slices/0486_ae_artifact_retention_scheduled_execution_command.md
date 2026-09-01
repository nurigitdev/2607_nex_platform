# Slice 0486: AE artifact retention scheduled execution command

Freeze the deterministic scheduled execution command payload that workers and
AG dispatch will share before any scheduler runtime is added.

## Scope

- Added runtime helpers:
  - `AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_COMMAND_SCHEMA_VERSION`
  - `build_artifact_retention_scheduled_execution_command(...)`
  - `validate_artifact_retention_scheduled_execution_command(...)`
  - `summarize_artifact_retention_scheduled_execution_command(...)`
- Added JSON Schema:
  - `contracts/schemas/generation/ae_artifact_retention_scheduled_execution_command.v1.schema.json`
- Added positive and negative contract fixtures.
- Added regression coverage for READY and NOOP commands, trigger
  normalization, dry-run purge request shape, summary matching, guardrails,
  metadata-only flags, unsafe payload rejection, and contract validation wiring.

## Decisions

- Scheduled execution commands are metadata-only command envelopes, not worker
  executions.
- READY commands may carry a purge route request, but the request is locked to
  `mode=DRY_RUN` with delete, storage, and database-row mutation flags false.
- NOOP commands must not carry an execution request.
- Scheduler status remains `DISABLED`; `scheduler_tick` and
  `operator_dispatch` are command trigger labels only.
- AG can dispatch through AE API semantics, but direct AE database writes remain
  forbidden.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
```
