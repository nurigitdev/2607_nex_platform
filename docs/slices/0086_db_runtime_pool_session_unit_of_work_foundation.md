# Slice 0086: DB runtime pool/session/unit-of-work foundation

## Intent

Slice 0086 prepares the platform for DB-intensive CX and AE work before
repository write-through expands. It adds service-aware SQLAlchemy pool settings,
statement-timeout hooks, and a small unit-of-work boundary for short
transactions.

## Runtime Behavior

`nex_runtime.database` now provides:

- `DatabasePoolSettings`
- `database_pool_settings(service_id, workload="api" | "worker")`
- service env prefix resolution for `nex-oa`, `nex-ag`, `nex-ae-api`,
  `nex-cx`, and `nex-mo`
- SQLAlchemy `QueuePool` settings for PostgreSQL engines
- PostgreSQL `statement_timeout` setup on new DBAPI connections
- `SqlAlchemyUnitOfWork` and `build_unit_of_work`

SQLite test engines keep lightweight SQLite pool behavior so regression tests do
not depend on PostgreSQL.

## Env Surface

Base service envs:

```text
NEX_<SERVICE>_DB_POOL_SIZE
NEX_<SERVICE>_DB_MAX_OVERFLOW
NEX_<SERVICE>_DB_POOL_TIMEOUT_SECONDS
NEX_<SERVICE>_DB_POOL_RECYCLE_SECONDS
NEX_<SERVICE>_DB_POOL_PRE_PING
NEX_<SERVICE>_DB_STATEMENT_TIMEOUT_MS
```

Worker overrides are supported with `DB_WORKER_*`, for example
`NEX_CX_DB_WORKER_POOL_SIZE` and `NEX_AE_DB_WORKER_STATEMENT_TIMEOUT_MS`.

## Defaults

| Workload | Pool Size | Max Overflow | Statement Timeout |
| --- | ---: | ---: | ---: |
| API request | 5 | 10 | 30000 ms |
| Worker/job | 3 | 3 | 60000 ms |

## Transaction Rule

Transactions must stay short. File I/O, provider HTTP calls, embedding/reranker
work, generation calls, and other slow external operations should happen outside
open DB transactions. Services should use short unit-of-work blocks around
durable state changes such as job status, event append, repository insert/update,
and final result publication.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_runtime_database.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
