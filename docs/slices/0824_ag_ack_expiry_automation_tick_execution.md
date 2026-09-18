# Slice 0824: AG acknowledgement expiry automation tick execution

## Objective

Connect the S83 policy and tick plan to the proven S82 reconciliation worker.

## Behavior

- Disabled automation is blocked before querying the state store.
- Enabled but unconfirmed execution returns `confirm_tick_required` and does
  not mutate state.
- Confirmed execution re-queries candidates and delegates to the S82 bounded
  worker.
- Successful transitions, idempotent no-ops, and compare-and-set conflicts are
  reported separately.
- The plan remains advisory, so changes between plan and execution are handled
  by the worker's database compare-and-set.
- No continuous loop, subprocess, route, or table is added.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_liveness_ack_expiry_automation_tick_execution.py -q --tb=short
```

Focused regression result: `18 passed`.

Full regression result: `5436 passed, 1 warning`.

- Statement coverage: `69401 / 70284 = 98.743668544761%`.
- Branch coverage: `16417 / 17068 = 96.185844855871%`.
- Automation module statement/branch coverage: `100% / 100%`.
