# Slice 0543: AE scheduler daemon CLI entrypoint foundation

## Scope

Add a development-safe AE scheduler daemon CLI entrypoint before enabling any
bounded loop or persistent daemon process.

## Implementation

- `nex_ae_api.artifact_retention_scheduler_daemon` owns the CLI plan contract,
  validator, summary, parser, and `main()` function.
- `scripts/daemon/run_ae_artifact_retention_scheduler_daemon.py` is the
  worktree wrapper that sets local service package paths before calling the
  module entrypoint.
- The CLI accepts test-profile runtime flags, `--max-cycles`, `--run-worker`,
  and `--summary`, but currently emits a plan-only JSON/summary payload.

## Guardrails

- The CLI foundation does not start the bounded loop.
- The CLI foundation does not run tick-once, enqueue JobQueue jobs, run workers,
  write a database, or enable physical delete automation.
- Ready runtime state is represented as `STARTING`; blocked/default runtime
  state is represented as `DISABLED`.
- Actual bounded loop behavior remains deferred to Slice 0544.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon.py -q
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon.py --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/daemon/run_ae_artifact_retention_scheduler_daemon.py --summary --enabled --explicit-opt-in --checked-at 2026-08-31T17:30:00Z --max-cycles 2
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/python -m nex_ae_api.artifact_retention_scheduler_daemon --summary --checked-at 2026-08-31T17:30:00Z
```
