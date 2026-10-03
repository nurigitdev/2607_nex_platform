# Slice 1255: OA service-principal durable repository

## Goal

Provide restart-safe memory and SQLAlchemy repository implementations for the
S126 principal and credential contracts.

## Implementation

- Added principal save, lookup, service-filtered list, and optimistic revision
  enforcement.
- Added credential create, lookup, principal-filtered list, lifecycle update,
  active-count, and optimistic revision enforcement.
- PostgreSQL credential creation locks the principal row and rechecks the
  active credential limit in the same transaction before insertion.
- Added JSONB-aware allowlist persistence and UTC timestamp conversion while
  keeping SQLite regression support.
- Extended the OA schema drift inventory to include the two S126 tables.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_service_principal_repository.py \
  --coverage-target services/nex-oa/nex_oa/service_principal_repository.py
```
