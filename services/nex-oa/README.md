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

Planned Slice 0193 minimum subject registry:

- Stable tenant reference: `{type: "oa.tenant", id: "..."}`
- Stable user subject reference: `{type: "oa.user", id: "..."}`
- Minimal status/display metadata for local development and downstream CX
  ownership references.
- Password login, external identity providers, role management, and full user
  profiles remain deferred until the ownership boundary is using stable subject
  ids.
