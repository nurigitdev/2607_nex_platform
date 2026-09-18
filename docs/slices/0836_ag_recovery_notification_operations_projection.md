# Slice 0836: AG recovery notification operations projection

## Objective

Provide a read-only operations projection for S84 policy, decision, and preview
status before integrating it into the versioned dashboard contract.

## Projection

The projection reports:

- policy enablement and delivery enablement;
- minimum severity, repeat window, and critical suppression bypass;
- current decision, severity, eligibility, and preview plan;
- protected preview path and source readiness;
- explicit absence of provider invocation and new tables.

Unavailable or malformed recovery source data produces a safe `DEGRADED` /
`SOURCE_UNAVAILABLE` projection with a normalized error code and no exception
detail.

## Integration Order

This Slice intentionally adds the standalone projection first. Slice 0837 will
atomically wire it into the dashboard together with the JSON Schema and
canonical fixture changes, preserving contract validity between commits.

## Guardrails

- Source recovery payloads and secrets are not copied.
- Delivery-ready status still performs no provider invocation.
- No database write, dispatch record, retry, retention, or deletion is added.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_recovery_notification_operations.py \
  -q --tb=short --cov=nex_ag.recovery_notification_operations \
  --cov-branch --cov-report=term-missing
```

Results:

- focused: `10 passed`; statement `100%`; branch `100%`;
- full regression: `5548 passed`, `1 warning`;
- full statement coverage: `70192 / 71075` (`98.757650369328%`);
- full branch coverage: `16545 / 17196` (`96.214235868807%`).

The warning is the existing Starlette `TestClient` deprecation warning.
