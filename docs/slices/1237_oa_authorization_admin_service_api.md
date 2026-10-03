# Slice 1237: OA authorization administration service and API

## Result

- Added path-authoritative role, group, group-member, and group-role mutation
  services and protected internal APIs.
- Separated mutation access (`authorization:admin`) from effective-grant and
  event reads (`authorization:read`); both also require `service:call`.
- Added strict operation-specific payload allowlists so caller-supplied tenant,
  subject, group, or role identities cannot override route ownership.
- Authorization mutations identify affected tenant subjects and revoke their
  active sessions. PostgreSQL/SQLite repository mutations, revocations, and
  privacy-safe events share one transaction.
- Memory runtime uses the same affected-subject and session-revocation
  semantics after its session registry is bound.
- Added effective-authorization and append-only authorization-event read APIs.
- No database table or migration was added in this Slice.

## Routes

- `PUT /internal/v1/auth/tenants/{tenant_id}/roles/{role_id}`
- `PUT /internal/v1/auth/tenants/{tenant_id}/groups/{group_id}`
- `PUT /internal/v1/auth/tenants/{tenant_id}/groups/{group_id}/members/{subject_id}`
- `PUT /internal/v1/auth/tenants/{tenant_id}/groups/{group_id}/roles/{role_id}`
- `GET /internal/v1/auth/tenants/{tenant_id}/subjects/{subject_id}/authorization`
- `GET /internal/v1/auth/tenants/{tenant_id}/authorization-events`

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_authorization_repository.py \
  --test tests/test_nex_oa_authorization_service.py \
  --test tests/test_oa_authorization_admin_api.py \
  --coverage-target services/nex-oa/nex_oa/authorization_repository.py \
  --coverage-target services/nex-oa/nex_oa/authorization_service.py \
  --coverage-target scripts/smoke/run_oa_authorization_admin_api.py \
  --smoke scripts/smoke/run_oa_authorization_admin_api.py
```

Observed result:

- OA regression: `381 passed, 2 skipped`
- Statement coverage: `98.56%` (required `95%`)
- Branch coverage: `96.70%` (required `94%`)
- Authorization repository: `100%` statement / `100%` branch
- Authorization service: `100%` statement / `100%` branch
- Protected smoke runner: `100%` statement / `100%` branch
- Contract validation: `134` schemas, `192` examples, `162` negative
  examples, and `7` OpenAPI documents
- Authorization administration smoke: `8/8` checks, `4` events
- Slice Gate: `5/5` commands passed
