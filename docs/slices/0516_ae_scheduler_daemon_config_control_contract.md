# Slice 0516: AE Scheduler Daemon Config/Control Contract

## Scope

Add the metadata-only daemon configuration and control-plan contract for the AE
artifact retention scheduler. This keeps S52 moving toward daemon operations
without starting a long-running process.

## Decisions

- Scheduler daemon auto-start remains disabled.
- Continuous loop execution remains disabled.
- `manual_tick_once` is the only control action that may become `READY`.
- `start_daemon` is explicitly `BLOCKED` with
  `daemon_disabled_by_policy`.
- `status_probe` and `stop_daemon` are metadata-only `NOOP` actions.
- Manual tick readiness requires operator dispatch admission, scheduler tick
  admission, an available lease repository, and an available JobQueue.

## Implementation

- Added daemon config and control-plan schema versions in
  `nex_ae_api.artifact_retention_scheduler`.
- Added builders, validators, action normalization, and summaries for:
  - daemon config
  - daemon control plan
- Reused the existing scheduler runtime config, lease repository capability
  check, metadata redaction posture, and no-daemon guardrails.

## Evidence

Regression tests cover:

- ready manual tick control plan;
- start-daemon block and status/stop no-op actions;
- lease repository and JobQueue readiness blocks;
- daemon config validation drift;
- control plan validation drift;
- protected redaction checks.

```bash
./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler.py -q --cov=nex_ae_api.artifact_retention_scheduler --cov-branch --cov-report=term-missing
```

Result: `55 passed`, module coverage `98%`.

## Guardrails

- No daemon process is started.
- No continuous loop is introduced.
- No direct AG database writes or direct AG job enqueues are allowed.
- No database URL, storage root, raw artifact payload, or raw execution payload
  is included in contract evidence.
