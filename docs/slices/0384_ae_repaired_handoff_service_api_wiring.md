# Slice 0384: AE Repaired Handoff Service API Wiring

## Scope

Wire the AE repaired response handoff service API using the source client from
Slice 0382 and the store from Slice 0383.

This slice uses deterministic fake CX clients for regression. PostgreSQL smoke
with the real `nex_ae_test` database is reserved for Slice 0385.

## Implemented

- Registered AE repaired handoff routes:
  - `POST /api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs`;
  - `GET /api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/{repaired_response_handoff_id}`.
- Added route flow:
  - validate service-claim auth for `nex-ae-api`;
  - reconcile payload/route `interaction_id`;
  - fetch and sanitize CX remediation detail and repaired generation record;
  - build `ae_repaired_response_handoff.v1`;
  - persist through the configured handoff store;
  - read back only within the same interaction scope.
- Registered the routes in `services/nex-ae-api/nex_ae_api/main.py`.
- Added regression coverage for successful create/read, path interaction
  defaulting, auth failures, interaction mismatch, sensitive payload rejection,
  CX not-ready errors, not-found reads, wrong-scope reads, and blank path
  validation.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_responses.py -q
31 passed, 1 warning in 1.20s
```

Targeted route coverage:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_responses.py -q --cov=nex_ae_api.repaired_responses --cov-branch --cov-report=term-missing
services/nex-ae-api/nex_ae_api/repaired_responses.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2780 passed, 1 warning
statement_coverage=98.6506%
branch_coverage=96.0442%
```

Recommended next slice:

```text
Slice 0385: AE repaired handoff PostgreSQL smoke evidence
```
