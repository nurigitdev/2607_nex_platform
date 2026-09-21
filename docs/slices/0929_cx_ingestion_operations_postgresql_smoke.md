# Slice 0929: CX durable ingestion operations PostgreSQL smoke evidence

## Goal

Prove that the S93 durable ingestion path works against the actual
`nex_cx_test` PostgreSQL database before closing the requirement.

## Implementation

- Adds an opt-in, test-only PostgreSQL smoke runner for the complete durable
  ingestion operations path.
- Applies pending NeX-CX migrations, creates an owner-scoped document through
  the real upload API, and verifies that admission persists both the common
  JobQueue record and `cx_ingest_runs` checkpoint record.
- Moves the job and run to an expired active lease, verifies the protected
  restart projection, and invokes the protected recovery API.
- Reads PostgreSQL directly to verify the resulting `QUEUED` job,
  `WAITING_RETRY` run, checkpoint version `2`, owner lineage, and
  `cx.ingestion.lease_recovered` operational event.
- Verifies that a different owner receives the collapsed `404` boundary and
  that private source text is absent from orchestration and event metadata.
- Deletes every probe row and reports the remaining row count. Cleanup uses
  both direct identifiers and the request/trace correlation keys, so a
  partially admitted upload is also removed. The quality gate executes the
  runner in its default protected `SKIPPED` mode.

## PostgreSQL DDL Correction

The first live migration attempt exposed a PostgreSQL-only foreign-key type
mismatch that SQLite regression could not detect:

- `service_jobs.job_id` is `TEXT`.
- `cx_ingest_runs.job_id` was declared as `UUID`.
- PostgreSQL correctly rejected the foreign key.

The ingestion migration now declares `cx_ingest_runs.job_id` as `TEXT`, which
matches the shared JobQueue contract and continues to accept the current
UUID-shaped identifiers without restricting future string identifiers. A
migration regression assertion fixes this compatibility requirement.

## Protected Execution

```bash
NEX_CX_INGESTION_OPERATIONS_POSTGRES_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test' \
./.venv/bin/python \
  scripts/smoke/run_cx_ingestion_operations_postgres_smoke.py
```

Observed evidence on 2026-09-21:

```text
status=PASS
database=nex_cx_test role=nex_cx_user
migration_applied=0923_cx_ingest_run_persistence
checks=17/17
job_status=QUEUED run_status=WAITING_RETRY checkpoint_version=2
cross_owner_hidden=true private_payload_absent=true
operational_event=cx.ingestion.lease_recovered
probe_residue=0
dgx_live_provider_required=false
```

DGX Spark and remote embedding, reranking, or generation providers are not
used by this persistence and operations smoke.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_cx_ingestion_run_migration.py \
  tests/test_cx_ingestion_operations_postgres_smoke.py \
  tests/test_nex_cx_ingestion_operations.py \
  tests/test_nex_cx_ingestion_durable_route.py
```

The protected PostgreSQL run passed all checks and left no probe rows. Slice
0930 can now close S93 using the accumulated audit, contract, regression, and
live PostgreSQL evidence.

Final quality gate:

```text
6670 passed, 1 known Starlette/httpx deprecation warning
statement=78900/79828=98.8372%
branch=18213/18890=96.4161%
contract validation: 85 schemas, 136 examples, 101 negative examples, 7 OpenAPI
protected default execution: SKIPPED
```
