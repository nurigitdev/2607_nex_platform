# Slice 0763: AG dispatch daemon control history read model

## Objective

Add the S77 read-model foundation for AG operator review escalation dispatch
daemon controls using `service_operational_events` as the source of record.

## Scope

- Added
  `ag_operator_review_escalation_dispatch_daemon_control_history_projection.v1`.
- Added `build_operator_review_escalation_dispatch_daemon_control_history_projection`.
- Reused the existing `service_operational_events` table and confirmed no
  dedicated control-history table is required in this slice.
- Projected only safe control summaries:
  - action, control status, route/method,
  - trace/request ids,
  - admission/error summaries,
  - plan/tick counters,
  - redaction flags.
- Added filtering and pagination through the existing operation query option
  helpers.
- Added degraded-source handling for unavailable operational event stores.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dispatch_daemon" --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `14 passed`; covered safe projection, filters, pagination, source
degradation, and redaction behavior.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5109 passed, 1 warning`; statement coverage `98.67%`
(`65474/66354`) and branch coverage `96.03%` (`15645/16292`).
