# Slice 0565: AE daemon supervisor service API wiring

## Scope

Expose AE-owned scheduler daemon supervisor controls and read models through
service APIs backed by the supervisor persistence store.

## Implementation

- Added `scheduler-daemon-supervisor-controls` dispatch route.
- Added `scheduler-daemon-supervisor-results` collection and detail routes.
- Added supervisor dispatch, collection, and detail response envelopes.
- Wired default supervisor persistence store construction from AE runtime
  persistence.
- Added regression coverage for auth, persistence, list/detail read models,
  invalid filters, missing details, and unavailable store responses.

## Guardrails

- Supervisor dispatch requires AE API auth and an AE-owned supervisor store.
- The default adapter remains `fake_dry_run`.
- `start_daemon` still returns blocked fake-adapter evidence and starts no OS
  process.
- AG can consume these routes later, but still cannot write AE persistence,
  enqueue AE jobs, or control AE daemon processes directly.
- Response payloads exclude database URLs, storage paths, raw artifact payloads,
  raw runtime payloads, and secrets.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py services/nex-ae-api/nex_ae_api/artifacts.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_routes.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_persistence.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_routes.py tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```

Result: `172 passed`.

## Next

- Slice 0566 should run protected PostgreSQL smoke evidence against
  `nex_ae_test` for the supervisor API path.
