# Slice 0551: AE scheduler daemon executable runtime boundary audit

## Scope

Start S56 by freezing the boundary for turning the AE artifact retention
scheduler daemon from a plan-first CLI into an explicitly executable bounded
runtime.

## Decisions

- AE remains the daemon process owner and artifact retention system of record.
- The default daemon mode remains disabled and the default CLI command remains
  plan-only.
- The first executable mode is protected bounded-loop execution only.
- Execution must require explicit opt-in, the test profile, explicit
  `max_cycles`, process lock/pid/run metadata, graceful shutdown handling, and
  PostgreSQL smoke evidence before enablement.
- Retention work still enters through finite JobQueue jobs; the daemon must not
  become a long-running JobQueue worker job.
- AG remains read-only and metadata-only for daemon lifecycle projection.
- Physical delete automation remains disabled by default.

## Evidence

- `scripts/smoke/run_ae_scheduler_daemon_executable_runtime_boundary_audit.py`
- `tests/test_ae_scheduler_daemon_executable_runtime_boundary_audit.py`
- `scripts/quality/run_quality_gate.sh`

## Next

- Slice 0552 defines the daemon CLI execute-mode contract/schema while keeping
  default execution disabled.
