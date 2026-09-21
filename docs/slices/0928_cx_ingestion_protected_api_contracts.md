# Slice 0928: CX ingestion protected API and observability contracts

## Goal

Expose durable ingestion progress and restart diagnostics through protected,
privacy-safe APIs while keeping lease recovery an explicit service operation.

## Implementation

- Adds owner-scoped run detail and per-document run history endpoints. Repository
  tenant/owner predicates enforce visibility, and cross-owner detail requests
  return the same not-found response as missing runs.
- Adds a service-token-protected, read-only restart plan endpoint with a bounded
  `1..500` scan limit.
- Adds an explicit service-token-protected expired-lease recovery endpoint. It
  delegates state changes to the Slice 0926 worker recovery operation rather
  than duplicating queue/run transitions in the HTTP layer.
- Records `cx.ingestion.lease_recovered` as a warning operational event with
  identifiers, states, checkpoint, retry time, failed step, and safe error code
  only. Event-store failure is visible in the response but does not roll back a
  completed queue/run recovery.
- Defines strict JSON Schemas, positive examples, targeted negative privacy
  fixtures, and OpenAPI 0.93.0 operations for all four endpoints.
- Updates the CX contract/API drift baseline to 31 runtime operations and 14 CX
  schemas, all with positive and negative fixture coverage.

No table or migration is added. PostgreSQL API/recovery evidence remains
protected until Slice 0929. DGX Spark is not required because no model provider
is called by these metadata-only operations.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_ingestion_operations.py \
  tests/test_nex_cx_ingestion_operations_contracts.py \
  tests/test_cx_ingestion_operations_contract_smoke.py \
  tests/test_nex_runtime_operational_events.py
./.venv/bin/python scripts/quality/validate_contracts.py
./.venv/bin/python \
  scripts/smoke/run_cx_ingestion_operations_contract_smoke.py --summary
```

Observed on 2026-09-21:

- Focused API/contract/taxonomy suite: `48 passed`; the new API module and
  shared operational-event module both reached `100%` statement and branch
  coverage in the focused measurement.
- Related durable-ingestion and contract-drift regression: `203 passed`.
- Contract validation: `85 schemas`, `136 positive examples`, `101 negative
  examples`, and `7 OpenAPI documents` passed.
- Deterministic protected API smoke: `PASS`, `10/10` checks, restart action
  `RECOVER_EXPIRED_LEASE`, recovery status `RETRY_SCHEDULED`.
- Full quality gate: `6665 passed`; statement coverage
  `98.83615932577506%`; branch coverage `96.4130549962912%`.
- PostgreSQL and DGX Spark were not invoked. Slice 0929 will run the protected
  API, restart, recovery, owner-isolation, and event evidence against the real
  `nex_cx_test` database.
