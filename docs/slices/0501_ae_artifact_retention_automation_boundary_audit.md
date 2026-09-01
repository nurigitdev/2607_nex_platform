# Slice 0501: AE Artifact Retention Automation Boundary Audit

## Scope

Slice 0501 starts S51 by freezing the safety boundary for AE artifact retention
automation before any scheduler daemon, tick planner, or physical purge adapter
is enabled.

## Decisions

- AE remains the artifact retention system of record.
- AG remains an operator projection/control surface that calls AE APIs and does
  not write AE persistence directly.
- The first automation mode is a scheduler tick that can only admit dry-run
  scheduled retention jobs.
- Physical delete automation remains disabled by default.
- Execute-mode physical deletion must require explicit operator, delete,
  storage mutation, and database row deletion guards.
- Any mutating smoke evidence in this track must connect to the real test DB
  when the protected smoke is enabled.

## Evidence

- `scripts/smoke/run_ae_artifact_retention_automation_boundary_audit.py`
- `tests/test_ae_artifact_retention_automation_boundary_audit.py`
- `scripts/quality/run_quality_gate.sh`

## Next

- Slice 0502 expands the scheduler runtime configuration while keeping the
  daemon disabled by default.
