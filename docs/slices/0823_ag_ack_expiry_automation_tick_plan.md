# Slice 0823: AG acknowledgement expiry automation tick plan

## Objective

Add a deterministic, read-only plan for each externally scheduled S83 tick.

## Behavior

- A disabled policy returns `DISABLED` without querying PostgreSQL.
- An enabled policy returns `IDLE` when no expired suppression is eligible.
- Eligible candidates produce `READY` with bounded, redacted summaries.
- The plan never mutates acknowledgement state.
- Raw comments and idempotency keys are excluded from candidate summaries.
- Stable inputs produce a stable UUID plan identifier.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_liveness_ack_expiry_automation_tick_plan.py -q --tb=short
```

Focused regression result: `12 passed`.

Full regression result: `5430 passed, 1 warning`.

- Statement coverage: `69386 / 70269 = 98.743400361468%`.
- Branch coverage: `16413 / 17064 = 96.184950773558%`.
- Automation module statement/branch coverage: `100% / 100%`.
