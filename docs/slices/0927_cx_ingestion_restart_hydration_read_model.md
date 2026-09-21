# Slice 0927: CX ingestion restart hydration and read model

## Goal

Reconstruct safe ingestion operating state after process restart and expose
owner-scoped progress without mutating durable records during discovery.

## Implementation

- Joins `cx.document_ingestion` JobQueue records to `cx_ingest_runs` by the
  unique job ID and classifies each pair as ready, retry-ready, waiting,
  active, expired-lease recovery, terminal, or reconciliation-required.
- Keeps hydration read-only. Worker claims and expired-lease mutations remain
  explicit Slice 0926 operations, preventing duplicate restart execution.
- Bounds restart scans to 100 records by default and 500 at maximum.
- Projects owner-visible run detail and document history only after repository
  tenant/owner filtering.
- Includes checkpoint, step status, safe output references, safe error codes,
  and retry/lease timestamps while excluding ownership internals and all raw
  text, prompt, vector, and provider payload fields.

No table or migration is added. PostgreSQL restart evidence remains protected
until Slice 0929, and DGX Spark is not required.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_ingestion_read_model.py \
  tests/test_cx_ingestion_restart_read_model_smoke.py
./.venv/bin/python \
  scripts/smoke/run_cx_ingestion_restart_read_model_smoke.py --summary
```

Observed on 2026-09-21:

- Focused read-model/smoke suite: `9 passed`; read-model statement and branch
  coverage: `100%`.
- Related durable-ingestion regression: `75 passed`.
- Deterministic restart smoke: `PASS`, `8/8` checks, action
  `RECOVER_EXPIRED_LEASE`, checkpoint version `1`.
- Full quality gate: `6650 passed`; statement coverage
  `98.83552953885965%`; branch coverage `96.41039236479321%`.
- PostgreSQL and DGX Spark were not invoked because hydration is read-only in
  this Slice. Actual test-database restart evidence remains in Slice 0929.
