# Slice 0921: CX durable ingestion orchestration boundary audit

## Goal

Freeze the S93 durability boundary before changing CX ingestion runtime or
schema.

## Findings

- Upload registration and extraction job state still depend on the process-local
  `ContentIngestionStore` document and job dictionaries.
- The existing shared JobQueue already provides durable enqueue, claim,
  completion, failure, retry, idempotency, and owner-lineage foundations.
- Processing-run persistence records final step outcomes, but it is not a
  claimable orchestration checkpoint that can resume after process restart.
- S92 private text/vector capabilities and owner enforcement remain the only
  allowed private-payload boundary.

## Decision

- Reuse `service_jobs` as the execution queue.
- Add a short CX-owned `cx_ingest_runs` table in Slice 0923 as the orchestration
  system of record. It stores metadata and checkpoints, never private document
  text or vectors.
- Execute bounded claim/run/checkpoint cycles. Resume from the last successful
  pipeline step after restart; stale work is recovered through explicit lease
  expiry and retry policy.
- Keep existing processing APIs compatible while moving orchestration state
  behind a repository port.
- Validate persistence against the actual `nex_cx_test` database before S93
  closure.

DGX Spark is not required for S93 durability work. Deterministic extractor and
provider doubles are sufficient; live model serving is orthogonal to queue,
checkpoint, restart, and owner-isolation behavior.

This slice adds no table, migration, route, or persistent record.

## Slice plan

1. Slice 0921: boundary audit.
2. Slice 0922: orchestration state and transition contract.
3. Slice 0923: durable run repository and migration.
4. Slice 0924: durable ingestion admission.
5. Slice 0925: checkpointed step coordinator.
6. Slice 0926: worker retry and recovery.
7. Slice 0927: restart hydration and read model.
8. Slice 0928: protected API, contract, and observability hardening.
9. Slice 0929: actual PostgreSQL smoke and privacy runbook.
10. Slice 0930: S93 closure.

## Verification

```bash
./.venv/bin/pytest -q tests/test_cx_durable_ingestion_boundary_audit.py
./.venv/bin/python \
  scripts/smoke/run_cx_durable_ingestion_boundary_audit.py --summary
```

Observed verification:

```text
boundary audit: PASS volatile=2 durable=3 table=cx_ingest_runs
focused tests: 5 passed; target statement/branch coverage: 100%
aggregate regression: 6545 passed, 1 known warning
statement=77609/78526=98.83223390978785%
branch=17965/18636=96.39944194033055%
contract validation: 82 schemas, 133 examples, 98 negative examples, 7 OpenAPI
```
