# Slice 1215: OA durable identity lifecycle repository

## Goal

Persist revision-guarded subject and membership transitions and append-only
lifecycle evidence without lengthening existing OA table names.

## Implementation

- `revision` is added to `oa_subjects` and `oa_tenant_memberships`, defaulting
  existing rows to revision 1.
- `oa_id_lifecycle_events` stores privacy-safe transition lineage with actor,
  request, and trace references. It stores no credentials or tokens.
- SQL updates guard previous state and expected revision in one statement.
- State update and event insert share one transaction and roll back together.
- The in-memory adapter follows the same result and conflict behavior.
- Table, index, and constraint names remain below PostgreSQL's identifier limit.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_identity_lifecycle_repository.py \
  --test tests/test_oa_identity_lifecycle_repository.py \
  --coverage-target services/nex-oa/nex_oa/identity_lifecycle_repository.py \
  --coverage-target scripts/smoke/run_oa_identity_lifecycle_repository.py \
  --smoke scripts/smoke/run_oa_identity_lifecycle_repository.py
```
