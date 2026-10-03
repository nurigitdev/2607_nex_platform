# Slice 1234: OA authorization persistence migration

## Result

- Added migration `1234_oa_group_role_authorization`.
- Added tenant-scoped `oa_roles`, `oa_groups`, `oa_group_members`, and
  `oa_group_roles` with revision, status, composite identity, and foreign-key
  constraints.
- Added append-only `oa_authz_events` without password, session, token,
  service-token, or database URL columns.
- Added bounded lookup indexes for tenant status, subject membership, role
  assignment, and event history.
- All declared table, index, and constraint names fit PostgreSQL's 63-byte
  identifier limit.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_authorization_persistence_migration.py \
  --coverage-target scripts/smoke/run_oa_authorization_persistence_migration.py \
  --smoke scripts/smoke/run_oa_authorization_persistence_migration.py
```
