# Slice 0923: CX durable ingestion run repository and migration

## Goal

Persist the Slice 0922 ingestion state contract behind an owner-scoped,
optimistic-locking repository.

## Implementation

- Adds the short `cx_ingest_runs` table for run status, six step checkpoints,
  owner lineage, retry timing, lease metadata, and checkpoint version.
- Reuses `service_jobs` for execution and `cx_content_objects` for document
  ownership; the new table does not duplicate queue payloads or document data.
- Enforces owner-scoped idempotency and verifies the run owner against the
  content-object owner with a PostgreSQL trigger.
- Implements matching in-memory and SQLAlchemy repositories. Updates require
  the previous checkpoint version and advance by exactly one.
- Keeps raw source bytes, extracted text, chunks, prompts, and vectors out of
  the orchestration table.

SQLite exercises repository semantics quickly. The migration is not applied to
the actual PostgreSQL test database in this Slice; protected PostgreSQL evidence
is reserved for Slice 0929 after admission, worker, recovery, and API wiring are
complete.

DGX Spark is not required.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_ingestion_orchestration_repository.py \
  tests/test_cx_ingestion_run_migration.py \
  tests/test_cx_ingestion_run_repository_contract.py
./.venv/bin/python \
  scripts/smoke/run_cx_ingestion_run_repository_contract.py --summary
```

Observed verification:

```text
repository contract: PASS checks=8/8 table=cx_ingest_runs
focused tests: 17 passed; repository focused coverage: 98%
aggregate regression: 6594 passed, 1 known warning
statement=78129/79052=98.83241410716997%
branch=18079/18754=96.40076783619494%
database audit: migrations=15 core_tables=18 issues=0
contract validation: 82 schemas, 133 examples, 98 negative examples, 7 OpenAPI
```
