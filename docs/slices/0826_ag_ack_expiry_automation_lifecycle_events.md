# Slice 0826: AG acknowledgement expiry automation lifecycle events

## Objective

Persist safe lifecycle evidence for externally scheduled acknowledgement expiry
automation ticks by reusing `service_operational_events`.

## Behavior

- A `run-once` invocation emits `started` before evaluating the tick.
- Successful execution emits `completed`; policy or confirmation guards emit
  `blocked`; unexpected execution errors emit `failed` before being re-raised.
- Read-only `plan` invocations do not create lifecycle events.
- Event details contain tick identifiers, statuses, and aggregate counts only.
  Raw comments, idempotency keys, payloads, database URLs, and exception text
  are excluded.
- Enabled executable runtime uses a `SqlAlchemyOperationalEventStore` backed by
  the same AG worker engine as the acknowledgement-state store.
- No new table is introduced.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_liveness_ack_expiry_automation_events.py \
  tests/test_nex_ag_liveness_ack_expiry_automation_cli.py \
  -q --tb=short
```

Focused regression result: `43 passed`.

Full regression result: `5461 passed, 1 warning`.

- Statement coverage: `69517 / 70400 = 98.745738636364%`.
- Branch coverage: `16431 / 17082 = 96.188970846505%`.
- Automation and CLI module statement/branch coverage: `100% / 100%`.
