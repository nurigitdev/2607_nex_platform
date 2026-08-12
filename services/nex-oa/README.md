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
- `GET /internal/v1/identity-auth-boundary`
- `POST /internal/v1/identity/memberships/ensure`
- `GET /internal/v1/identity/memberships/tenants/{tenant_id}/subjects/{subject_id}`
- `POST /internal/v1/auth/user-sessions/issue`
- `POST /internal/v1/auth/user-sessions/introspect`
- `GET /internal/v1/auth/user-sessions/{session_id}`
- `GET /internal/v1/auth/session-credential-delivery-boundary`

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

Slice 0241 identity/auth boundary audit:

- `GET /internal/v1/identity-auth-boundary` exposes the service-token protected
  OA/AE/CX authority split for identity and browser auth.
- OA owns stable tenant/user refs, the subject registry, and future session
  issuance/introspection. AE owns the browser session facade and route guard, but
  does not own durable identity authority or password verification. CX consumes
  owner scope and ACLs, but does not issue browser sessions.
- The report includes only enum/boolean decision evidence and omits raw tokens,
  cookies, passwords, provider endpoints, and database URLs.

Slice 0242 tenant membership persistence:

- `oa_tenant_memberships` links stable `oa.tenant` and `oa.user` refs to
  membership status, roles, scopes, and safe metadata.
- `POST /internal/v1/identity/memberships/ensure` creates the subject registry
  entry first, then stores an idempotent membership snapshot.
- The membership boundary intentionally excludes raw tokens, browser cookies,
  passwords, external identity profiles, emails, phone numbers, and provider
  secrets.

Slice 0243 OA user-session issuance:

- `oa_user_sessions` stores browser-safe session snapshots linked to active OA
  tenant memberships.
- `POST /internal/v1/auth/user-sessions/issue` issues a session only when the
  membership exists, is active, and grants the requested scopes.
- Session responses deliberately omit raw tokens and cookies. AE facade
  delegation remains the next integration step after PostgreSQL smoke evidence.

Slice 0244 OA session PostgreSQL smoke:

- `scripts/smoke/run_oa_session_postgres_smoke.py` applies `nex-oa` migrations
  and exercises membership ensure, session issue, session readback, DB
  observation, and smoke-row cleanup against the protected `test` profile.
- The smoke runner is skipped by default and requires
  `NEX_OA_SESSION_POSTGRES_SMOKE=1` for write execution.

Slice 0245 OA-AE session credential delivery boundary:

- `GET /internal/v1/auth/session-credential-delivery-boundary` freezes the
  delegation decision before AE starts using OA-backed sessions.
- OA owns session issuance, persistence, introspection, and revocation. AE owns
  browser login composition, HttpOnly cookie set/delete, route-guard
  introspection calls, and browser-safe session projection.
- Browser JSON must not include raw user tokens, service credentials, password
  material, database URLs, or cookie values.

Slice 0246 OA session introspection API:

- `POST /internal/v1/auth/user-sessions/introspect` lets AE validate an opaque
  OA session id with a service-token protected internal call.
- The response returns `active`, `inactive_reason`, and the browser-safe session
  snapshot when one exists. It never returns raw user tokens, service
  credentials, passwords, or cookie values.
- `ACTIVE` sessions become inactive when their `expires_at` timestamp has
  passed; `EXPIRED`, `REVOKED`, and missing sessions return explicit inactive
  reasons.
