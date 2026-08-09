# Slice 0185: CX Processing PostgreSQL Smoke Evidence

## Scope

Slice 0185 adds guarded PostgreSQL smoke evidence for CX processing run
persistence.

Implemented:

- optional smoke script:
  `scripts/smoke/run_cx_processing_postgres_persistence_smoke.py`
- quality gate skip summary wiring
- PostgreSQL test smoke suite stage wiring
- SQLite-backed regression for the smoke executor path
- persistence decision/audit status update to `postgres_smoke_ready`

## Decision

The smoke remains opt-in and test-profile only. The default quality gate invokes
the script in summary mode, where it reports `SKIPPED` unless
`NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE=1` is set.

When enabled, the smoke runs migrations, creates a temporary uploaded document,
persists a queued processing run, upserts it to a succeeded run, persists a
failed run, checks repository round trips, verifies latest-run ordering, and
confirms private source/output/error payloads are absent from persisted rows.

## Operational Command

```bash
NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_cx_processing_postgres_persistence_smoke.py --summary
```

The broader PostgreSQL test smoke suite now includes the same stage:

```bash
NEX_POSTGRES_TEST_SMOKE_SUITE=1 \
./.venv/bin/python scripts/smoke/run_postgres_test_smoke_suite.py --summary
```

## Next Slice

Recommended next slice:

- `0186_cx_processing_persisted_read_model_query_foundation`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
pass
```
