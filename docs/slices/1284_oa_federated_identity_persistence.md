# Slice 1284: OA federated identity persistence migration and repository

## Outcome

- Added `oa_fed_providers` and `oa_fed_identities`; both table names are under
  20 characters and all identifiers remain below PostgreSQL's 63-byte limit.
- Provider trust persists issuer, client audience, discovery URL, lifecycle
  status, and optimistic revision without a client or provider secret column.
- External identities persist only a 64-character subject digest and canonical
  OA tenant/subject references. The raw external subject is absent by design.
- Foreign keys bind links to OA subjects, while a unique constraint prevents
  one OA subject from being linked twice to the same provider.
- Memory and SQLAlchemy repositories support restart-safe reads, filtering,
  optimistic updates, immutable internal-subject mapping, and fail-closed
  database error handling.

Actual PostgreSQL migration and cleanup evidence remains scheduled for Slice
1290; this Slice uses SQLite for deterministic repository regression.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_federated_identity_repository.py \
  --coverage-target services/nex-oa/nex_oa/federated_identity_repository.py \
  --coverage-target scripts/smoke/run_oa_federated_identity_persistence.py \
  --smoke scripts/smoke/run_oa_federated_identity_persistence.py
```
