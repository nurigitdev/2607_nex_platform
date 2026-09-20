# Slice 0887: AG audit retention contract and index hardening

## Goal

Freeze the S89 retention operations boundary in JSON Schema and OpenAPI, and
add deterministic PostgreSQL indexes for bounded oldest-first candidate reads.

## Implementation

- Added a strict JSON Schema for the retention operations projection and purge
  execution response. Raw source payloads, archive object references,
  credentials, and purge confirmations remain forbidden in responses.
- Registered positive operations and dry-run examples plus negative object-ref
  and confirmation-leak fixtures in the canonical contract indexes.
- Added OpenAPI paths for the protected retention projection and purge command,
  including strict request and response component schemas.
- Added `idx_ag_evt_retention_time` and `idx_ag_exp_retention_time`. Both names
  are at most 30 characters and match the candidate store's ascending stable
  ordering.
- Applied migration `0887_ag_retention_candidate_indexes` to the actual
  `nex_ag_test` database and directly verified both PostgreSQL indexes.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_audit_retention.py \
  tests/test_nex_ag_audit_retention_archive.py \
  tests/test_nex_ag_audit_retention_purge.py \
  tests/test_nex_ag_audit_retention_operations.py \
  tests/test_nex_ag_audit_retention_contracts.py \
  --cov=nex_ag.audit_retention \
  --cov=nex_ag.audit_retention_archive \
  --cov=nex_ag.audit_retention_purge \
  --cov=nex_ag.audit_retention_operations \
  --cov-branch --cov-report=term-missing

./.venv/bin/python scripts/quality/validate_contracts.py contracts
```

Observed verification:

```text
retention tests: 110 passed, 1 known warning
retention modules statement/branch: 100%
contract_validation=pass schemas=81 examples=132 negative_examples=95 openapi=7
PostgreSQL: nex_ag_test migration present=true indexes=2
aggregate regression: 6127 passed, 1 known warning
statement=74392/75273=98.829593612584%
branch=17446/18096=96.408045977011%
```
