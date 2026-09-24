# Slice 0990: CX Async Generation PostgreSQL Recovery Smoke

## Goal

Prove the S99 asynchronous generation and recovery boundary against the actual
CX test database while remote providers are unavailable.

## Protected Evidence

The opt-in smoke targets only `nex_cx_user@nex_cx_test`, runs current
migrations, and uses a deterministic in-process generation provider. It checks:

- durable API admission and SQL job enqueue;
- bounded worker success and private output persistence;
- retryable provider failure followed by successful retry;
- expired worker lease recovery followed by successful execution;
- queued cancellation converging the generation record to `FAILED`;
- restart reads, idempotent terminal replay, and cross-owner hiding;
- metadata-only operational events and zero database residue after cleanup.

The live database run also exposed and fixed a replay serialization defect:
SQL-backed execution timestamps are now passed through FastAPI's standard JSON
encoder before the terminal replay response is returned.

No embedding, reranker, or generation endpoint is contacted by this smoke.

## Execution

```bash
NEX_CX_ASYNC_GENERATION_POSTGRES_SMOKE=1 \
NEX_CX_ASYNC_GENERATION_POSTGRES_SMOKE_PROFILE=test \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:<password>@127.0.0.1:5432/nex_cx_test' \
./.venv/bin/python \
  scripts/smoke/run_cx_async_generation_postgres_smoke.py --summary
```

The ordinary unit and regression paths remain mock-backed and do not require
PostgreSQL or remote provider connectivity.
