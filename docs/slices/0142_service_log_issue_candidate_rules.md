# Slice 0142: Service Log Issue Candidate Rules

## Scope

Slice 0142 connects AG issue candidate projection with structured service log
signals from the service-local `service_log_entries` stores.

Implemented:

- `error_service_logs_present.v1`
- `critical_service_logs_present.v1`
- `recent_failures.logs` in the AG dashboard snapshot projection
- `log_source_statuses` in dashboard and issue candidate projections
- contract schema/example updates for the new log failure surface

## Behavior

AG now treats `ERROR` and `CRITICAL` structured service logs as operational
issue candidate signals. Candidates are grouped by service and severity, and
include safe diagnostic signal fields:

- `count`
- `threshold`
- `log_ids`
- `logger_names`

Log source handling is intentionally conservative:

- `READY` log sources can contribute failure-log candidates.
- `UNAVAILABLE` log sources mark the projection `DEGRADED` through the
  existing operations source issue rule.
- `NOT_CONFIGURED` log sources do not degrade the dashboard yet, because
  structured service logs are still being rolled out service by service.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_contract_validation.py
```

Contract validation:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

