# Slice 1233: OA group and role authorization domain

## Goal

Define one tenant-scoped, revision-guarded domain contract for roles, groups,
group members, and group-role assignments before persistence is added.

## Result

- Role and group identifiers use a bounded canonical lowercase format.
- Role scopes are validated as `resource:action`, deduplicated, and sorted.
- All four records carry immutable tenant identity and optimistic revisions.
- Status is restricted to `ACTIVE` or `DISABLED`.
- Display text is bounded and metadata recursively rejects credential, token,
  cookie, authorization, password, and secret fields.
- Create requires revision zero; update requires the exact current revision and
  fails closed on stale or cross-tenant identity.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_authorization.py \
  --test tests/test_oa_group_role_authorization_domain.py \
  --coverage-target services/nex-oa/nex_oa/authorization.py \
  --coverage-target scripts/smoke/run_oa_group_role_authorization_domain.py \
  --smoke scripts/smoke/run_oa_group_role_authorization_domain.py
```
