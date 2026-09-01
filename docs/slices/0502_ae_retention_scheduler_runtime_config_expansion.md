# Slice 0502: AE Retention Scheduler Runtime Config Expansion

## Scope

Slice 0502 expands the AE artifact retention scheduler config read-model with
disabled-by-default runtime knobs that later scheduler ticks can consume.

## Runtime Knobs

- `automation_profile`: `disabled-dry-run-local-v1`
- `scheduler_tick_interval_seconds`: `900`
- `scheduler_tick_jitter_seconds`: `60`
- `scheduler_tick_lock_ttl_seconds`: `600`
- `scheduler_tick_stale_after_seconds`: `3600`
- `scheduler_tick_max_jobs_per_tick`: `1`
- `scheduler_tick_batch_window_enforced`: `true`
- `scheduler_tick_timezone`: `Asia/Seoul`
- `scheduler_tick_window_start`: `02:00`
- `scheduler_tick_window_end`: `05:00`

## Guardrails

The scheduler daemon is still disabled, the default execution mode is still
`DRY_RUN`, physical delete automation is still disabled, and runtime config
validation now rejects missing, extra, or drifted scheduler knobs.

## Evidence

- `services/nex-ae-api/nex_ae_api/artifacts.py`
- `tests/test_nex_ae_artifacts.py`
- `scripts/quality/run_quality_gate.sh`
