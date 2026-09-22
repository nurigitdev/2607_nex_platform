# Slice 0948: CX Retrieval Operations Observability

## Goal

Make permission-filtered retrieval outcomes and actionable failures visible in
the shared operational-event stream without persisting private retrieval
payloads or allowing observability outages to fail the primary request.

## Implementation

- Emits deterministic `cx.retrieval.package_observed` events after successful
  package persistence for both legacy and hardened runtime modes.
- Emits deterministic `cx.retrieval.package_failed` events for validated
  package-build failures and persistence failures.
- Records only status, policy, permission-policy version, rerank state, bounded
  counts, failure stage, status code, and retryability. Query text, evidence
  text, user IDs, document IDs, hashes, and exception details are excluded.
- Uses the shared `OperationalEventEmitter.safe_emit` boundary, so an event
  store outage never changes a successful retrieval response or masks the
  canonical retrieval problem response.
- Normalizes unexpected persistence exceptions to the redacted, retryable
  `CX_RETRIEVAL_PERSISTENCE_UNAVAILABLE` problem.
- Does not emit events from unauthenticated requests using untrusted identity
  headers.
- Adds deterministic authenticated API contract evidence covering success,
  idempotent event identity, redacted failure evidence, and correlation IDs.
- Adds no table or migration. In PostgreSQL service mode the existing shared
  operational-event store receives these events automatically.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_retrieval_observability.py \
  tests/test_nex_cx_hybrid_retrieval_package.py \
  tests/test_nex_cx_retrieval.py \
  tests/test_cx_retrieval_operations_observability.py \
  --cov=nex_cx.retrieval_observability \
  --cov=run_cx_retrieval_operations_observability \
  --cov-branch --cov-report=term-missing
```

Focused results:

- `140 passed`.
- Retrieval observability module statement/branch coverage: 100%/100%.
- Contract runner statement/branch coverage: 100%/100%.
- Deterministic contract evidence: `10/10` checks passed.

Full quality-gate results:

- `7121 passed`.
- Repository statement coverage: 98.88%.
- Repository branch coverage: 96.55%.
- Contract validation: 85 JSON Schemas, 136 examples, 101 negative examples,
  and 7 OpenAPI documents passed.

PostgreSQL and remote embedding/reranker access were intentionally not invoked
and remain deferred to the protected Slice 0949 smoke.
