# Slice 0511: AE Scheduler Daemon Boundary Audit and Refactoring Checkpoint

## Scope

Start S52 by freezing the AE artifact retention scheduler daemon boundary before
adding lease, runner, or loop code.

## Boundary Decision

- S52 starts from the closed S51 retention automation baseline.
- Scheduler daemon auto-start remains disabled.
- The first S52 runtime path is a manual once runner before any continuous
  daemon loop.
- The once runner must reuse the existing scheduler tick planner and JobQueue
  admission path.
- Physical delete automation remains disabled and execute mode still requires
  operator approval plus delete, storage mutation, and database row deletion
  guards.
- AG may observe scheduler runtime posture through AE APIs, but it must not
  write AE persistence or enqueue AE jobs directly.

## Refactoring Checkpoint

Before long-running scheduler behavior is added, S52 should introduce the
lease/lock repository before daemon execution and keep long-running scheduler
code out of the large artifact surface. The preferred path is:

```text
lease/lock contract -> lease repository -> manual once runner -> protected
PostgreSQL smoke -> dry-run loop planner -> CLI harness -> AG projection
```

This gives us duplicate tick protection before any loop can run repeatedly, and
keeps the current `nex_ae_api.artifacts` module from absorbing daemon lifecycle
logic.

The implementation order is intentionally conservative: manual once runner
before any continuous daemon loop, lease/lock repository before daemon
execution, and keep long-running scheduler code out of the large artifact
surface.

## Evidence

The boundary audit runner is:

```text
scripts/smoke/run_ae_artifact_retention_scheduler_daemon_boundary_audit.py
```

It checks required files, S51 closure continuity, scheduler daemon defaults,
tick admission reuse, physical delete safety, protected PostgreSQL evidence
hooks, AG read-only operator boundaries, docs, and quality-gate wiring.

```text
ae_artifact_retention_scheduler_daemon_boundary_audit=pass
```

## Next

- Slice 0512: Scheduler lease/lock contract foundation.
- Slice 0513: Scheduler lease repository adapter.
- Slice 0514: Scheduler tick once runner.
- Slice 0515: Scheduler tick once PostgreSQL smoke evidence.
