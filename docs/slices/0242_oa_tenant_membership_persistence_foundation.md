# Slice 0242: OA Tenant Membership Persistence Foundation

## Scope

Add the durable OA membership layer needed before OA can issue browser-safe
sessions. The slice keeps password login and external identity providers
deferred.

## Implemented

- Added `oa_tenant_memberships` in the `nex-oa` migration set.
- Added in-memory and SQLAlchemy membership registries backed by the existing
  subject registry.
- Added service-token protected membership ensure/read endpoints:
  - `POST /internal/v1/identity/memberships/ensure`
  - `GET /internal/v1/identity/memberships/tenants/{tenant_id}/subjects/{subject_id}`
- Kept membership records limited to stable refs, status, roles, scopes, and
  safe metadata.

## Boundary

- OA owns membership persistence and will use it for session issuance in Slice
  0243.
- AE continues to own browser composition and route guards.
- CX continues to consume owner-scope claims and ACLs, but does not manage OA
  membership state.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_oa_memberships.py tests/test_nex_oa_auth_boundary.py tests/test_database_schema_foundation.py -q`
  - Result: `30 passed, 1 warning`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1725 passed, 1 warning`
  - Coverage: statement `98.07%`, branch `94.05%`
  - Contract validation: `pass` with 49 schemas, 78 examples, 54 negative
    examples, and 7 OpenAPI specs.
