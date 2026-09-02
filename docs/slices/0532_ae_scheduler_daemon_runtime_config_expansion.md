# Slice 0532: AE scheduler daemon runtime config expansion

## Scope

Add the AE-owned runtime enablement config contract for the artifact retention
scheduler daemon without starting a daemon process or opening a continuous loop.

## Runtime Config

- `nex-ae-api` remains the source of record for daemon runtime configuration.
- Runtime profile support is limited to `test`.
- Runtime enablement is disabled by default.
- `enabled=true` without `explicit_opt_in=true` is reported as `BLOCKED` with
  `explicit_opt_in_required`.
- `enabled=true` with `explicit_opt_in=true` is reported as `READY`, but the
  loop policy still keeps auto-start, start controls, stop controls, and
  continuous loop execution disabled.
- The contract carries interval, jitter, backoff, lease TTL, stale-window, and
  batch-window settings as metadata-only evidence.

## Guardrails

- One-cycle execution must be added before any loop can run.
- Lease and fencing-token checks remain required before ticks.
- Scheduler execution remains `DRY_RUN`.
- Physical delete automation remains disabled.
- No database URL, storage path, raw artifact payload, or raw execution payload
  is emitted in the runtime config.
- AG may later project this config, but must not write AE persistence or enqueue
  AE jobs directly.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py -q --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_ae_scheduler_daemon_runtime_boundary_audit.py --summary
```
