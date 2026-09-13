# Slice 0715: AG escalation dispatch execution transition planner

## Intent

Convert safe execution results into dispatch state-machine action payloads before
introducing a run-once worker.

## Implementation

- Added
  `ag_operator_review_escalation_dispatch_execution_transition_plan.v1`.
- Added `build_dispatch_execution_transition_plan(...)`.
- The planner maps safe execution results to existing dispatch actions:
  `START`, `SUCCEED`, `FAIL`, and `RETRY`.
- Terminal, in-progress, unsupported, live-deferred, and max-attempt-exhausted
  rows are represented as safe skipped or blocked plans.

## Boundary

Slice 0715 still does not mutate dispatch rows by itself. It produces action
payloads that are valid for the existing S71 dispatch state machine.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```
