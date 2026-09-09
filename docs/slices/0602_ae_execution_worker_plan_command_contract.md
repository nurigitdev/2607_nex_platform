# Slice 0602: AE execution worker plan/command contract

## Scope

Add the AE-owned operator-control execution worker plan and command contracts
without enabling worker execution side effects.

## Decision

- No new database table is introduced in Slice 0602.
- Worker plan/command contracts reuse the S60 operator-control execution
  request, state, transition, and persistence boundaries.
- A worker plan is `READY` only when the source execution state is `ADMITTED`,
  the execution mode is `fake_dry_run_supervisor_persistent_dispatch`, and a
  supervisor command preview is available.
- A worker command is `READY` only from a ready worker plan; otherwise it is
  `BLOCKED` and carries no supervisor commands.
- The first worker mode is
  `fake_dry_run_supervisor_persistent_dispatch_worker`.

## Implementation

- Added worker plan and command schema versions to
  `services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py`.
- Added builder, validator, summary, and summary-line helpers for:
  - `operator_control_execution_worker_plan`
  - `operator_control_execution_worker_command`
- Added regression coverage for ready start, restart stop-then-start,
  non-admitted blocked state, validator mutations, non-mapping inputs, and
  default command time behavior.

## Guardrails

- Slice 0602 does not add a route, invoke a worker, call a supervisor adapter,
  write PostgreSQL rows, enqueue JobQueue work, start/stop subprocesses, or
  delete artifacts.
- Worker commands continue to require explicit later execution.
- Physical deletion and real subprocess control remain disabled.
- The eventual PostgreSQL smoke should reuse the existing S60 execution
  state/transition tables rather than adding long table names.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_contract.py
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_contract.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
./.venv/bin/python scripts/quality/check_coverage_thresholds.py reports/coverage/coverage.json 95 85
```

- Targeted regression: `42 passed`.
- Full regression/quality gate: exit code `0`.
- Coverage evidence: statement `98.56%`, branch `95.67%`.

## Next

- Slice 0603 should harden the worker state-transition contract so an admitted
  execution state can be represented as executing and terminal worker progress
  without weakening the S60 idempotency and projection guardrails.
