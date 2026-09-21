# Slice 0924: CX durable ingestion admission

## Goal

Make successful upload registration idempotently admit both the existing shared
JobQueue job and the durable ingestion run.

## Implementation

- Reuses the canonical `cx.document_ingestion` job and increases its retry
  budget to the orchestration policy default of three attempts.
- Enqueues the job by deterministic job ID/upload idempotency key, then creates
  the owner-scoped run by the same upload key.
- Preserves the existing upload response contract; orchestration metadata is not
  injected into the document registration response.
- Requires queue and run repository dependencies together. Partial success is
  recovered by retrying the same owner/upload key because both writes are
  idempotent and identity checked.
- Wires PostgreSQL deployments to the SQLAlchemy run repository and local/mock
  deployments to the in-memory repository.

This Slice performs deterministic memory and route regression only. The actual
PostgreSQL admission path remains protected until Slice 0929. DGX Spark is not
required.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_ingestion_admission.py \
  tests/test_nex_cx_ingestion_durable_route.py \
  tests/test_cx_durable_ingestion_admission_smoke.py
./.venv/bin/python \
  scripts/smoke/run_cx_durable_ingestion_admission_smoke.py --summary
```

Observed verification:

```text
admission smoke: PASS checks=8/8 jobs=1 runs=1
focused tests: 17 passed; admission and runtime-builder branch coverage: 100%
aggregate regression: 6611 passed, 1 known warning
statement=78229/79153=98.83264058216366%
branch=18098/18772=96.40954613253783%
contract validation: 82 schemas, 133 examples, 98 negative examples, 7 OpenAPI
```
