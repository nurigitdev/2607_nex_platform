# Slice 0603: AE execution worker state transition hardening

## Scope

Harden the AE-owned operator-control execution worker state-transition
contract before adding worker execution side effects.

## Decision

- No new database table is introduced in Slice 0603.
- Worker transition plans are metadata-only contracts derived from the Slice
  0602 worker command.
- A ready worker command produces exactly one execution state path:
  `ADMITTED -> EXECUTING -> SUCCEEDED` or
  `ADMITTED -> EXECUTING -> FAILED`.
- A blocked worker command produces no transition rows and is represented as a
  blocked transition plan.
- The eventual persistence wiring should reuse the existing
  `ae_daemon_operator_control_execution_states` and
  `ae_daemon_operator_control_execution_transitions` tables.

## Implementation

- Added the worker transition-plan schema version and status constants.
- Added deterministic worker transition-plan id generation.
- Added builder, validator, summary, and summary-line helpers for
  `operator_control_execution_worker_transition_plan`.
- Added regression coverage for success terminal plans, failure terminal plans,
  blocked commands, restart stop-then-start supervisor commands, invalid
  terminal statuses, invalid transition paths, malformed payloads, and default
  timestamp behavior.

## Guardrails

- Slice 0603 does not invoke the worker, supervisor adapter, subprocess control,
  JobQueue enqueue, database write, or physical deletion.
- Transition plans cap the worker state-machine path at two transitions.
- Invalid transition paths fail at the worker transition-plan boundary instead
  of leaking lower-level state-transition errors.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan.py
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

- Targeted regression: `31 passed`.
- Full regression/quality gate: `4219 passed`, exit code `0`.
- Coverage evidence: statement `98.56%`, branch `95.66%`.

## Next

- Slice 0604 should add the fake dry-run worker adapter that consumes a ready
  worker command and its transition plan, while still avoiding real subprocess
  control and physical deletion.
