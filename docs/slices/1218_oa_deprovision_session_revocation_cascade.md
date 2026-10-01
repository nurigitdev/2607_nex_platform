# Slice 1218: OA deprovision session revocation cascade

## Goal

Invalidate active user sessions atomically when authoritative subject or direct
membership access is disabled.

## Behavior

- Subject `DISABLED` and `DELETED` transitions revoke matching active sessions.
- Membership `DISABLED` transitions revoke matching active sessions.
- Revocation is tenant and subject scoped. Other users and already expired or
  revoked sessions remain unchanged.
- PostgreSQL state transition, session revocation, and lifecycle event insert
  share one transaction. Any failure rolls back all three effects.
- In-memory runtime follows the same projection and reports the count of newly
  revoked sessions.
- Reactivation does not restore old sessions; users must authenticate again.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_identity_lifecycle_repository.py \
  --test tests/test_oa_deprovision_session_cascade.py \
  --coverage-target services/nex-oa/nex_oa/identity_lifecycle_repository.py \
  --coverage-target scripts/smoke/run_oa_deprovision_session_cascade.py \
  --smoke scripts/smoke/run_oa_deprovision_session_cascade.py
```
