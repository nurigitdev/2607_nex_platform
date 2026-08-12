# nex-oa

Slice 0001 shell for NeX Open Auth.

Owned database env: `NEX_OA_DATABASE_URL`.

Current endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `POST /api/v1/auth/service-token`
- `POST /api/v1/auth/introspect`
- `GET /internal/v1/auth/service-claim`
- `POST /internal/v1/subject-registry/ensure`
- `GET /internal/v1/subject-registry/tenants/{tenant_id}`
- `GET /internal/v1/subject-registry/tenants/{tenant_id}/subjects/{subject_id}`

Slice 0193 minimum subject registry:

- Stable tenant reference: `{type: "oa.tenant", id: "..."}`
- Stable user subject reference: `{type: "oa.user", id: "..."}`
- Minimal status/display metadata for local development and downstream CX
  ownership references.
- Password login, external identity providers, role management, and full user
  profiles remain deferred until the ownership boundary is using stable subject
  ids.
- PostgreSQL persistence uses `oa_tenants` and `oa_subjects`; local regression
  tests cover the same repository boundary with SQLite.
- The registry intentionally excludes raw identity payloads such as passwords,
  tokens, emails, phone numbers, raw external profiles, and secrets.

Slice 0198 resolver client:

- `nex_runtime.subject_resolver.HttpSubjectRegistryResolver` can verify or
  ensure OA subject refs through the subject registry endpoints.
- The resolver propagates service tokens, request ids, and trace headers while
  rejecting unsupported ownership metadata before making OA calls.

Slice 0232 browser user-session/token foundation:

- `nex_runtime.auth` can issue and validate mock user tokens separately from
  service tokens.
- User claims carry tenant, user, roles, scopes, audience, and `token_use=user`.
- `contracts/schemas/service/nex_oa/browser_session.v1.schema.json` freezes the
  browser-safe session snapshot without raw tokens, passwords, or service
  credentials.
