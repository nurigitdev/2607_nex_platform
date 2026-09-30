# Slice 1161: S116 MO durable provider telemetry closure

## Goal

Close S116 with deterministic contract, persistence, runtime, restart,
authenticated API, privacy, actual PostgreSQL, and Full Gate evidence before
MO GPU and model runtime observability work begins.

## Result

- Closed provider telemetry persistence around one compact MO-owned table and
  a stable four-field logical identity.
- Preserved the established 26-field authenticated wire projection while
  adding atomic counters, monotonic diagnostics, and restart-safe PostgreSQL
  recovery.
- Kept memory mode deterministic and process-local while PostgreSQL mode uses
  the shared MO API engine/session pool.
- Proved concurrent aggregation and restart recovery in SQLite regression and
  actual `nex_mo_user@nex_mo_test` evidence, with targeted zero-residue cleanup.
- Registered every S116 evidence runner in the Full Gate; the protected
  PostgreSQL runner remains opt-in and requires no DGX provider call.
- Handed GPU, loaded-dtype, model-resource, and accelerator telemetry to S117.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s116_mo_durable_provider_telemetry_closure.py
./.venv/bin/python \
  scripts/smoke/run_s116_mo_durable_provider_telemetry_closure.py --summary
scripts/quality/run_quality_gate.sh
```

## Quality Evidence

- Focused closure regression: `6 passed`; machine-checkable closure passed
  `8/8` evidence runners and `5/5` components with all `26` wire fields and
  `24` persistence columns aligned.
- Full Gate: `9,274 passed`, `7` protected smoke skips, and `123` warnings in
  `1,129.67s`.
- Repository coverage remained above policy at statement `98.75%` and branch
  `97.00%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- AE Web Node regression passed `293/293` tests.
- All ten S116 evidence runners completed in the Full Gate; the protected
  PostgreSQL runner skipped by default while the separately executed Slice
  1160 evidence remained `11/11` with cleanup residue `0`.
