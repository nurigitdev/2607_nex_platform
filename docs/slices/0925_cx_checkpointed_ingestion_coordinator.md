# Slice 0925: CX checkpointed ingestion step coordinator

## Goal

Execute one durable ingestion step at a time and persist each successful
checkpoint before moving to the next step.

## Implementation

- Maps the six canonical ingestion steps to the existing extraction, chunking,
  lexical-index, embedding-index, summary, and summary-embedding services.
- Accepts only an already claimed run and verifies the lease owner through the
  Slice 0922 transition contract.
- Advances `checkpoint_version` exactly once per successful or skipped step and
  persists through the Slice 0923 repository.
- Detects already materialized outputs and records a skipped checkpoint instead
  of recomputing them.
- Stores only a compact `type:id` metadata reference in the orchestration run;
  raw text, prompts, vectors, and provider output remain outside the table.
- Converts step and repository failures into metadata-only errors for the
  retry/recovery worker introduced in Slice 0926.

This Slice uses deterministic handlers for regression. It performs no actual
PostgreSQL migration and does not require DGX Spark.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_ingestion_coordinator.py \
  tests/test_cx_ingestion_checkpoint_coordinator_smoke.py
./.venv/bin/python \
  scripts/smoke/run_cx_ingestion_checkpoint_coordinator_smoke.py --summary
```

Observed on 2026-09-21:

- Focused coordinator suite: `15 passed`; coordinator statement and branch
  coverage: `100%`.
- Related ingestion regression: `186 passed`.
- Deterministic smoke: `PASS`, `8/8` checks, six steps, terminal checkpoint
  version `7`.
- Full quality gate: `6626 passed`; statement coverage
  `98.83294010774802%`; branch coverage `96.40842822177291%`.
- PostgreSQL and DGX Spark were not invoked because this Slice introduces the
  deterministic checkpoint coordinator only. The persisted PostgreSQL path is
  reserved for Slice 0929 after worker and recovery wiring are complete.
