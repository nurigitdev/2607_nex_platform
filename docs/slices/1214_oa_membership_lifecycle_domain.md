# Slice 1214: OA membership lifecycle domain

## Goal

Define revision-guarded direct tenant membership transitions independently of
storage and transport.

## Behavior

- Direct membership transitions between `ACTIVE` and `DISABLED` only.
- Changed state requires a reason and advances revision once; same-state calls
  are idempotent.
- Disabling membership explicitly requests revocation of matching active user
  sessions.
- Re-enabling membership never restores previously revoked sessions. A fresh
  login is required.
- Stale expected revisions fail closed before any persistence work.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_identity_lifecycle.py \
  --test tests/test_oa_membership_lifecycle_domain.py \
  --coverage-target services/nex-oa/nex_oa/identity_lifecycle.py \
  --coverage-target scripts/smoke/run_oa_membership_lifecycle_domain.py \
  --smoke scripts/smoke/run_oa_membership_lifecycle_domain.py
```
