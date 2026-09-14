# Slice 0746: AG dispatch execution daemon runtime projection

## Intent

Expose a dashboard-ready read model for AG escalation dispatch daemon tick
runtime without adding a route, writer, table, or background loop.

## Implementation

- Added
  `build_operator_review_escalation_dispatch_daemon_runtime_projection`.
- The projection summarizes tick status, blocked reasons, provider modes,
  dry-run count, candidate totals, processed totals, and latest tick items.
- Policy output is sanitized to operational fields only; env maps and secrets are
  not surfaced.
- Worker run internals and provider payloads are excluded from the runtime
  projection.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `174 passed`, `98%` coverage for `nex_ag.operations`.
