# Slice 1184: MO operations integration service

## Goal

Compose catalog/alias, readiness, durable telemetry, and runtime observation
facts into one safe operational snapshot without adding persistence.

## Result

- Added an integration service that reads each source independently so one
  failure cannot erase diagnostics from the other sources.
- Used active catalog bindings as the capability identity axis and joined the
  corresponding readiness, telemetry, and runtime facts.
- Propagated bounded `force_refresh` only to readiness and runtime services;
  catalog and durable telemetry remain read-only.
- Mapped stale, malformed, missing, unconfigured, and failed sources to safe
  `UNKNOWN`, `DEGRADED`, or `UNAVAILABLE` states without exception details.
- Added no database table and emitted only allowlisted operational metadata.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_operations_service.py
./.venv/bin/python scripts/smoke/run_mo_operations_integration_service.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```

## Executed evidence

- Integration evidence passed with four sources, three ready capabilities, and
  zero private fields.
- Focused operations regression passed `47` tests; both the service and domain
  modules reached `100%` statement and branch coverage.
- NeX-MO Slice Gate passed `887` tests with `3` protected PostgreSQL skips;
  aggregate statement coverage was `99.86%` and branch coverage was `99.49%`.
