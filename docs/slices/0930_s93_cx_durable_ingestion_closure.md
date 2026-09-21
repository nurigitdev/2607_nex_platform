# Slice 0930: S93 CX durable ingestion orchestration closure

## Closure result

S93 closes as `READY_FOR_S94` with
`CX_DURABLE_INGESTION_ORCHESTRATION_READY` readiness.

- The existing `service_jobs` JobQueue remains the execution queue and the
  short `cx_ingest_runs` table is the owner-scoped orchestration system of
  record.
- Six ordered pipeline steps persist metadata-only checkpoints with optimistic
  version checks. Raw source bytes, extracted text, prompts, and vectors remain
  outside orchestration state.
- Upload admission idempotently creates the queue job and run. A partial write
  can be reconciled by retrying the same owner and upload key.
- The bounded worker synchronizes queue/run retries, resumes from the last
  successful checkpoint, and recovers expired leases explicitly.
- Restart discovery is read-only. Owner APIs hide cross-owner resources, while
  protected service APIs expose restart plans and explicit recovery operations.
- Recovery emits the privacy-safe `cx.ingestion.lease_recovered` operational
  event.

## Actual PostgreSQL evidence

The protected Slice 0929 runner connected to the actual
`nex_cx_user@nex_cx_test` database, applied migration
`0923_cx_ingest_run_persistence`, exercised upload admission, JobQueue and run
persistence, restart planning, expired-lease recovery, owner isolation, and
operational-event persistence, and passed all 17 checks. It verified
checkpoint version `2`, `QUEUED`/`WAITING_RETRY` synchronized states, no private
payload in orchestration metadata, and zero remaining probe rows.

The live run also detected and corrected the PostgreSQL-only foreign-key type
mismatch: `cx_ingest_runs.job_id` is `TEXT`, matching `service_jobs.job_id`.
SQLite remains the fast regression database, while this PostgreSQL proof covers
the dialect-specific migration and runtime path.

## Decisions

- The versioned SQL plus `schema_migrations` runner remains the single migration
  history.
- Checkpoint mutations require optimistic `checkpoint_version` progression.
- Retry timing is synchronized across the common job and the ingestion run.
- Hydration never mutates state; recovery requires an explicit operation.
- S92 owner-scoped private storage remains the only private-payload boundary.
- Provider-backed pipeline execution, a continuous worker process, and
  production object/vector adapters remain deferred.
- DGX Spark is not required for S93 because this requirement closes durable
  queue, checkpoint, restart, and recovery behavior without model inference.
- The next requirement is identified only as S94; its title and slice scope are
  intentionally left for the next review.

## Verification

```bash
./.venv/bin/pytest -q tests/test_s93_cx_durable_ingestion_closure.py
./.venv/bin/python \
  scripts/smoke/run_s93_cx_durable_ingestion_closure.py --summary
```

Observed on 2026-09-21:

- Focused closure suite: `6 passed`; the closure runner reached `100%`
  statement coverage with no uncovered measured branches.
- Closure evidence: `PASS`, deterministic evidence `8/8`, six pipeline steps,
  PostgreSQL evidence checks `17/17`, next requirement `S94`.
- Full quality gate: `6676 passed`; statement coverage `98.84%`; branch
  coverage `96.42%`.
- Contract validation: `85 schemas`, `136 positive examples`, `101 negative
  examples`, and `7 OpenAPI documents` passed.
- The protected PostgreSQL runner remained `SKIPPED` in the default quality
  gate. Its actual `nex_cx_test` evidence was produced and cleaned in Slice
  0929 and is required by this closure.

The closure adds no table, index, route, or migration.
