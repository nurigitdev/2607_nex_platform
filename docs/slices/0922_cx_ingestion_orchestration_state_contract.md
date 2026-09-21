# Slice 0922: CX ingestion orchestration state and transition contract

## Goal

Define and validate the durable ingestion run shape before persistence wiring.

## Contract

- Run states: `QUEUED`, `RUNNING`, `WAITING_RETRY`, `SUCCEEDED`, `FAILED`, and
  `CANCELLED`.
- Ordered checkpoint steps: extraction, chunking, lexical index, embedding
  index, summary, and summary embedding.
- Claims require a worker identity and lease expiry. Mutations can enforce an
  expected `checkpoint_version` to reject stale writers.
- Retryable failures enter `WAITING_RETRY`; exhausted or permanent failures are
  terminal. Requeue resumes the same failed step without erasing attempt counts.
- Tenant and owner references are mandatory and immutable through transitions.
- Checkpoints contain metadata references and error codes only. Unknown fields,
  raw payloads, source text, vectors, prompts, and free-form error details are
  rejected by the strict shape validator.

The contract is storage-neutral and adds no table, migration, route, or database
write. Slice 0923 will persist this shape behind a repository port.

DGX Spark and PostgreSQL are not required for this pure transition contract.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_ingestion_orchestration.py \
  tests/test_cx_ingestion_orchestration_contract.py
./.venv/bin/python \
  scripts/smoke/run_cx_ingestion_orchestration_contract.py --summary
```

Observed verification:

```text
contract evidence: PASS checks=8/8 steps=6 transitions=10
focused tests: 32 passed; orchestration module statement/branch coverage: 100%
aggregate regression: 6577 passed, 1 known warning
statement=77911/78829=98.83545395729998%
branch=18046/18718=96.40987284966343%
contract validation: 82 schemas, 133 examples, 98 negative examples, 7 OpenAPI
```
