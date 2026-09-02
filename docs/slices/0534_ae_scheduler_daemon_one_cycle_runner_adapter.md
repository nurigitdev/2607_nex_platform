# Slice 0534: AE scheduler daemon one-cycle runner adapter

## Scope

Add the AE-owned one-cycle daemon runner adapter for artifact retention
scheduler runtime. The adapter is still not a continuous daemon loop: it builds
the pure loop plan first, then calls the existing tick-once runner only when
the loop plan is `READY`.

## Behavior

- `READY` loop plans run exactly one tick through the existing lease-protected
  tick-once runner.
- `DISABLED` and `BLOCKED` loop plans return `SKIPPED` before any tick.
- `NOOP` loop plans return `NOOP` before any tick.
- Tick-once results are propagated as the one-cycle result status, including
  `SUCCEEDED`, `NOOP`, `SKIPPED`, and `FAILED`.
- The adapter uses the same normalized run time for loop planning and tick-once
  execution.

## Guardrails

- A loop plan is required before tick execution.
- Tick-once execution requires a `READY` loop plan.
- Non-ready loop plans cannot include a tick result.
- The adapter still starts no daemon process and no continuous loop.
- Physical delete automation remains disabled.
- Result payloads remain metadata-only and safe for later AG projection.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py -q --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
```
