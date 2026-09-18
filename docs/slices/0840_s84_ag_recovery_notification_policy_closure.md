# Slice 0840: S84 AG recovery notification policy closure

## Purpose

Close S84 by proving that dispatch recovery signals can be evaluated and
presented as redacted operator notifications without crossing into external
delivery.

## Closure

- Defines enabled-by-default evaluation with delivery disabled by default.
- Applies minimum severity, acknowledgement repeat suppression, active TTL
  suppression, and critical bypass rules deterministically.
- Produces redacted notification plans with no raw recovery plan, comment,
  idempotency key, provider payload, endpoint, token, or database URL.
- Exposes a protected read-only preview route and dashboard projection.
- Freezes the static OpenAPI, operations JSON Schema, and canonical fixture.
- Reuses `ag_op_review_ack_state` and `service_operational_events`; no table or
  index is added.
- Records actual `nex_ag_test` migration, persisted suppression read,
  side-effect absence, and cleanup evidence without accepting a skipped smoke.
- Records privacy regression and operator runbook evidence across eight policy
  and source states.

## Operational Boundary

S84 may report `READY` when policy authorizes delivery, but it still sets
`performed=false` and `provider_invocation_performed=false`. External provider
selection, retry, dispatch persistence, and delivery execution remain later
requirements.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_s84_ag_recovery_notification_policy_closure.py --summary
./.venv/bin/python scripts/quality/validate_contracts.py
./.venv/bin/pytest \
  tests/test_s84_ag_recovery_notification_policy_closure.py \
  -q --tb=short \
  --cov=run_s84_ag_recovery_notification_policy_closure \
  --cov-branch --cov-report=term-missing
```

Closure result:

```text
s84_ag_recovery_notification_policy_closure=pass slice_range=0831-0840 postgres=True privacy=True delivery=False
```

Contract validation result:
`contract_validation=pass schemas=77 examples=123 negative_examples=87 openapi=7`.

- Closure runner: `7 passed`; statement/branch coverage `100% / 100%`.
- S84 focused regression: `58 passed`, `1 warning`.
- Full regression: `5579 passed`, `1 warning`.
- Statement coverage: `70498 / 71381` (`98.762976142111%`).
- Branch coverage: `16581 / 17232` (`96.222144846797%`).

The warning is the existing Starlette `TestClient` deprecation warning.
