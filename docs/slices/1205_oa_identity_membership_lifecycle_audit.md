# Slice 1205: OA identity and membership lifecycle audit

## Goal

Audit the stable subject and tenant-membership lifecycle before changing
credential or session behavior.

## Result

- Stable tenant/user references, tenant-scoped storage, and role/scope-backed
  session admission are implemented.
- Subject and membership status values exist, but no explicit transition API,
  optimistic update policy, or transition lineage exists.
- Session issuance rejects inactive memberships, but deprovisioning does not
  cascade revocation to sessions that were already issued.
- Roles and scopes exist as membership attributes; a group registry and group
  membership model do not yet exist.
- Bootstrap `ensure` routes use the generic service-call scope rather than a
  dedicated identity bootstrap/admin policy.
- Subject and membership snapshots expose stale capability metadata: password
  login and OA session issuance are implemented but still reported as deferred.
  This projection-only refactor is assigned to Slice 1209.
- These are quantified S122+ hardening inputs, not reasons to mutate lifecycle
  state during S121. No table or migration is added.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_oa_identity_lifecycle_audit.py --summary

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_identity_lifecycle_audit.py \
  --coverage-target services/nex-oa/nex_oa/identity_lifecycle_audit.py \
  --coverage-target scripts/smoke/run_oa_identity_lifecycle_audit.py \
  --smoke scripts/smoke/run_oa_identity_lifecycle_audit.py
```
