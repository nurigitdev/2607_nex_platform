# Slice 0908: CX contract and API drift audit

## Goal

Separate basic contract validation from coverage completeness across CX runtime
routes, OpenAPI operations, schemas, and indexed fixtures.

## Findings

- All indexed schemas/examples and OpenAPI documents validate, but four of 29
  service-local runtime routes are missing from CX OpenAPI:
  - processing read
  - processing enqueue
  - processing run
  - source-file materialization read
- All 11 CX service schemas have positive fixtures; 10 have negative fixtures.
  `source_ownership_boundary_decision.v1` lacks a negative fixture.
- Seven core generation schemas have both positive and negative fixtures.
- CX OpenAPI still reports version `0.0.0-slice0003`.

The audit passes as executable evidence, while contract readiness remains
`GAPS_CONFIRMED` with six drift items.

## Decision

S92 contract hardening should add the four operations, the missing negative
fixture, a maintained API version, and validator checks that fail when a CX
schema is absent from the positive or negative indexes.

This slice changes no public schema, route, table, or migration.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_cx_contract_api_drift_audit.py --summary
./.venv/bin/pytest -q tests/test_cx_contract_api_drift_audit.py \
  --cov=nex_cx.contract_api_drift_audit \
  --cov=run_cx_contract_api_drift_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
audit: PASS readiness=GAPS_CONFIRMED runtime_routes=29 drift=6
focused tests: 4 passed; target statement/branch coverage: 100%
aggregate regression: 6311 passed, 1 known warning
statement=76095/76976=98.85548742465184%
branch=17718/18368=96.46123693379791%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
