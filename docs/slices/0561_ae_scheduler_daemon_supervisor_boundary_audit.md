# Slice 0561: AE scheduler daemon supervisor boundary audit

## Scope

Start S57 by freezing the boundary for AE scheduler daemon supervisor readiness
before `start_daemon` or continuous-loop process supervision is opened.

## Decisions

- AE remains the daemon process owner, supervisor owner, and artifact retention
  system of record.
- AG remains read-only and metadata-only for daemon and supervisor operations.
- The default supervisor mode remains disabled, and daemon start remains blocked
  until a schema-bound supervisor contract and PostgreSQL smoke evidence exist.
- The first supervisor implementation should be an injectable metadata-only
  fake/dry-run adapter, not an OS process manager.
- Production continuous daemon start remains disabled by default.
- Supervisor start/stop must preserve test profile, explicit opt-in, bounded
  `max_cycles`, lease, process lock, pid/run metadata, graceful shutdown,
  redacted evidence, and finite JobQueue retention work guardrails.

## Refactoring Checkpoint

- Keep CLI bounded execution in `nex_ae_api.artifact_retention_scheduler_daemon`.
- Keep long-running process ownership out of `artifacts.py`.
- Reuse bounded-loop, process lock, run metadata, shutdown, and run-store
  contracts from S56.
- Do not host the daemon as a long-running JobQueue worker job.
- Keep AG as an AE API consumer; AG must not write AE daemon persistence,
  enqueue AE jobs, or control local daemon processes directly.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_scheduler_daemon_supervisor_boundary_audit.py tests/test_ae_scheduler_daemon_supervisor_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ae_scheduler_daemon_supervisor_boundary_audit.py -q
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ae_scheduler_daemon_supervisor_boundary_audit.py --cov=run_ae_scheduler_daemon_supervisor_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ae_scheduler_daemon_supervisor_boundary_audit.py --summary
```

## Next

- Slice 0562 defines the schema-bound supervisor command/result contract while
  keeping daemon start disabled by default.
