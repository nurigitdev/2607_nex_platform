# Slice 0005 OA Service Token Mock

Status: Implemented.

Backlog candidate: `S1-005` OA service token mock and claim validation.

Requirement coverage: `OA-FR-002`, `OA-FR-003`, `PLAT-FR-002`.

## Scope

Slice 0005 adds a deterministic local-mock service-claim baseline:

- `services/_shared/nex_runtime/auth.py` for mock service token issue and
  validation.
- `POST /api/v1/auth/service-token` on `nex-oa`.
- `POST /api/v1/auth/introspect` on `nex-oa`.
- `GET /internal/v1/auth/service-claim` on every backend service.
- `contracts/schemas/common/service_claims.v1.schema.json`.
- Positive and negative service-claim fixtures.
- OpenAPI bootstrap paths for the mock auth endpoints.

The token format is intentionally named `nex-mock-service.*` so it cannot be
confused with a production signed token.

## Evidence

Quality gate target:

```text
pytest with statement coverage and branch coverage
coverage threshold check
contract validation with auth fixtures
```

## Follow-Up

Slice 0006 should add the MO mock provider alias registry and reuse the
service-claim validator for protected mock provider access.
