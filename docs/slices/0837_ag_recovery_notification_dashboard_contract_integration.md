# Slice 0837: AG recovery notification dashboard and contract integration

## Objective

Integrate the S84 recovery notification operations projection into the AG
dashboard and freeze the protected preview surface in versioned contracts.

## Runtime Integration

The operator review escalation dispatch dashboard now derives
`recovery_notification` from the already-built `daemon_recovery` projection.
The field is present for ready, empty, and degraded dispatch-store paths and
retains the request trace identifier when supplied.

This remains a read-only projection. A delivery-ready policy does not invoke a
provider, persist a dispatch record, or create a table.

## Contract Integration

- The operations JSON Schema requires `recovery_notification`.
- The canonical dashboard fixture includes the default preview-only result.
- The static OpenAPI contract exposes the protected preview `GET` route and its
  redacted response schema.
- Contract tests validate the schema, fixture, route, and component together.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
./.venv/bin/pytest \
  tests/test_nex_ag_recovery_notification_contracts.py \
  tests/test_nex_ag_recovery_notification_preview_api.py \
  -q --tb=short --cov=nex_ag.operations \
  --cov=nex_ag.recovery_notification_operations \
  --cov-branch --cov-report=term-missing
```

Results:

- contract validation: `pass` (`77` schemas, `123` examples, `87` negative
  examples, `7` OpenAPI documents);
- focused: `8 passed`, `1 warning`;
- full regression: `5552 passed`, `1 warning`;
- full statement coverage: `70196 / 71079` (`98.757720283065%`);
- full branch coverage: `16545 / 17196` (`96.214235868807%`).

The warning is the existing Starlette `TestClient` deprecation warning.
