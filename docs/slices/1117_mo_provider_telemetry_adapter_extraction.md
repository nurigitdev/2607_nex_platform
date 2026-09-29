# Slice 1117: MO provider telemetry adapter extraction

## Goal

Move provider request telemetry behind an explicit store boundary without
prematurely selecting or adding durable persistence.

## Result

- `nex_mo.provider_telemetry` owns buckets, recording, snapshots, locking, and
  elapsed-time observation.
- `ProviderTelemetryStore` defines the replaceable persistence boundary.
- The default `InMemoryProviderTelemetryStore` preserves existing process-local
  behavior and deterministic tests.
- `nex_mo.remote_provider` retains telemetry compatibility exports and builds
  execution configs before delegating snapshots.
- Endpoint values, API keys, payloads, model paths, and error details remain
  outside telemetry projection.
- Restart-safe persistence remains explicit S116 work; no table is added here.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_telemetry_extraction.py \
  tests/test_nex_mo_remote_provider.py \
  --cov=nex_mo.provider_telemetry \
  --cov=run_mo_provider_telemetry_extraction \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_telemetry_extraction.py --summary
```
