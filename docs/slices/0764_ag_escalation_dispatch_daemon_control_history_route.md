# Slice 0764: AG dispatch daemon control history route

## Objective

Expose the S77 dispatch daemon control history read model through a protected
AG operations API route.

## Scope

- Added `GET /admin/v1/operator-review/dispatch-daemon/controls`.
- Reused `service_operational_events` as the source of record; no new table is
  required.
- Added explicit `action` and `control_status` filter normalization.
- Preserved standard operations query options: `since`, `until`, `sort`,
  `cursor`, and `limit`.
- Returned `DEGRADED` projections when the operational event store is
  unavailable instead of leaking implementation errors.
- Kept response content limited to safe control summaries and redaction flags.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dispatch_daemon" --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `15 passed`; covered protected access, successful history projection,
normalized filters, invalid query handling, degraded source projection, and
redaction behavior.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5110 passed, 1 warning`; statement coverage `98.67%`
(`65508/66388`) and branch coverage `96.03%` (`15659/16306`).
