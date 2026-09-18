# Slice 0829: AG acknowledgement expiry automation privacy and runbook

## Objective

Close the S83 privacy, concurrency, and operator-response evidence gap before
the automation closure checkpoint.

## Privacy Evidence

- Exercises disabled plan, unconfirmed run, confirmed run, compare-and-set
  conflict, and state-store failure paths.
- Verifies lifecycle events and operations projections contain aggregate counts
  and normalized failure codes only.
- Rejects raw comments, raw idempotency keys, credentials, provider keys,
  database URLs, access tokens, and exception details.
- Confirms the external scheduler posture starts neither an in-process loop nor
  a supervised subprocess.
- Rechecks all S83 documents, actual PostgreSQL non-skip evidence, short reused
  table names, and quality-gate wiring.

## Operator Runbook

| Signal | Response |
| --- | --- |
| `automation_disabled` | Review policy, scheduler, and test evidence before enabling. |
| `confirm_tick_required` | Review the plan, then repeat with explicit `--confirm-tick`. |
| Database unavailable | Inspect NeX-AG database health, migrations, and worker pool before retrying. |
| Event source unavailable | Restore `service_operational_events` persistence before scheduling. |
| CAS conflict | Let the next bounded tick re-read the current state; do not overwrite a renewal. |
| Zero candidates | Treat it as a successful idle tick. |
| Scheduler invocation failed | Inspect the exit code and safe lifecycle failure code before retrying. |

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_ack_expiry_automation_privacy_runbook_evidence.py \
  --summary
./.venv/bin/pytest \
  tests/test_ag_ack_expiry_automation_privacy_runbook_evidence.py \
  -q --tb=short
```

Evidence result:
`ag_ack_expiry_automation_privacy_runbook=pass surfaces=8 privacy=True conflict=True runbook=True`.

Focused regression result: `6 passed`.

Full regression result: `5488 passed, 1 warning`.

- Statement coverage: `69869 / 70752 = 98.751978742650%`.
- Branch coverage: `16493 / 17144 = 96.202753149790%`.
- Privacy/runbook runner statement/branch coverage: `100% / 100%`.
