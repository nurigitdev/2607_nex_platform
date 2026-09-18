# Slice 0834: AG recovery notification redacted plan

## Objective

Turn an S84 eligibility decision into a deterministic, metadata-only
notification preview without constructing or sending a provider payload.

## Plan Contract

- `PREVIEW_ONLY`: eligible while delivery is disabled.
- `READY`: policy authorizes future delivery, but S84 still sends nothing.
- `SUPPRESSED`: acknowledgement or active suppression blocks the notification.
- `NOT_REQUIRED`: no eligible recovery signal exists.

The plan uses a deterministic UUID, fixed operator audience, the in-product
operations dashboard preview channel, and a template-generated title/summary.
Service, worker, and trace identifiers accept only safe characters and bounded
lengths.

## Guardrails

- Raw recovery plans and provider payloads are never included.
- Raw action titles, comments, idempotency keys, endpoints, tokens, and database
  URLs are discarded.
- `READY` does not invoke a provider or persist a dispatch.
- No new table, route, retry, retention, or deletion behavior is added.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_recovery_notification_policy.py \
  tests/test_nex_ag_recovery_notification_eligibility.py \
  tests/test_nex_ag_recovery_notification_plan.py \
  -q --tb=short --cov=nex_ag.recovery_notification_policy \
  --cov-branch --cov-report=term-missing
```

Focused regression result: `33 passed`.

Full regression result: `5534 passed, 1 warning`.

- Statement coverage: `70146 / 71029 = 98.756845795379%`.
- Branch coverage: `16537 / 17188 = 96.212473818943%`.
- Policy/eligibility/plan module statement/branch coverage: `100% / 100%`.
