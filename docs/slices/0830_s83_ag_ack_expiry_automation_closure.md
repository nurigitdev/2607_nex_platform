# Slice 0830: S83 AG acknowledgement expiry automation closure

## Purpose

Close S83 by proving that acknowledgement expiry reconciliation can be invoked
as a disabled-by-default, externally scheduled, bounded run-once operation.

## Closure

- Reuses `ag_op_review_ack_state` and `service_operational_events`; no table or
  index is added.
- Keeps cadence ownership outside the NeX-AG process and starts neither a
  continuous loop nor a supervised subprocess.
- Requires both explicit automation enablement and `--confirm-tick` before a
  run can mutate acknowledgement state.
- Bounds each run through a configured batch limit and preserves the S82
  compare-and-set conflict guard.
- Uses the worker database pool and always disposes the CLI engine.
- Publishes safe lifecycle events and a dashboard projection for disabled,
  waiting, healthy, attention, and degraded states.
- Records actual `nex_ag_test` migration, transition, lifecycle-event, and
  cleanup evidence without accepting a skipped smoke.
- Records privacy, concurrency, failure normalization, and operator runbook
  evidence.

## Operational Boundary

An external scheduler may invoke:

```bash
python -m nex_ag.liveness_ack_expiry_automation_cli \
  --run-once --confirm-tick --summary
```

The scheduler owns cadence and retry policy. S83 does not add an in-process
timer, long-running loop, daemon supervisor, retention policy, or physical
deletion path.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_s83_ag_ack_expiry_automation_closure.py --summary
./.venv/bin/pytest \
  tests/test_s83_ag_ack_expiry_automation_closure.py -q --tb=short
```

Closure result:
`s83_ag_ack_expiry_automation_closure=pass slice_range=0821-0830 scheduler=external_scheduler postgres=True privacy=True loop=False`.

S83 focused regression result: `84 passed`.

Contract validation result:
`contract_validation=pass schemas=77 examples=123 negative_examples=87 openapi=7`.

Full regression result: `5495 passed, 1 warning`.

- Statement coverage: `69955 / 70838 = 98.753493887462%`.
- Branch coverage: `16497 / 17148 = 96.203638908328%`.
- New closure runner statement/branch coverage: `100% / 100%`.
