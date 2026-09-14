# Slice 0765: AG dispatch daemon operations dashboard integration

## Objective

Surface dispatch daemon control history in the AG operations dashboard without
introducing a dedicated control-history table.

## Scope

- Added `daemon_controls` under the existing
  `operator_review_escalation_dispatches` dashboard section.
- Reused `service_operational_events` as the control history source.
- Added dashboard source status reporting for
  `operator_review_dispatch_daemon_controls`.
- Kept dashboard output to safe control summaries:
  - status/action rollups,
  - recent safe control items,
  - source status,
  - route paths for history, tick-plan, and tick-once controls.
- Propagated control-history source degradation to the top-level dashboard
  `projection_status`.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dispatch_daemon or dashboard or unavailable_sources" --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `45 passed, 145 deselected, 1 warning`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5112 passed, 1 warning in 300.52s`.

Coverage: statement `98.67%` (`65535/66417`), branch `96.03%`
(`15669/16316`).
