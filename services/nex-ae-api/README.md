# nex-ae-api

Slice 0001 shell for NeX Agent Experience API.

Owned database env: `NEX_AE_DATABASE_URL`.

Current endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `GET /internal/v1/auth/service-claim`
- `GET /api/v1/auth/session`
- `POST /api/v1/auth/session/login`
- `POST /api/v1/auth/session/logout`
- `POST /api/v1/workspaces`
- `GET /api/v1/workspaces/{workspace_id}`
- `GET /api/v1/workspaces/{workspace_id}/activity`
- `POST /api/v1/uploads`
- `POST /api/v1/uploads/files`
- `GET /api/v1/uploads/{upload_handoff_id}`
- `GET /api/v1/workspaces/{workspace_id}/documents`
- `GET /api/v1/documents/summary-search`
- `GET /api/v1/documents/{document_id}`
- `POST /api/v1/artifact-handoffs`
- `GET /api/v1/artifact-handoffs/{artifact_handoff_id}`
- `POST /api/v1/artifacts`
- `GET /api/v1/artifacts/{artifact_id}`
- `GET /api/v1/artifacts/{artifact_id}/versions`
- `POST /api/v1/artifacts/{artifact_id}/render-jobs`
- `GET /api/v1/artifact-render-jobs/{render_job_id}`
- `GET /api/v1/artifact-files/{artifact_file_id}`
- `GET /api/v1/artifact-files/{artifact_file_id}/preview`
- `GET /api/v1/artifact-files/{artifact_file_id}/download`
- `GET /api/v1/compatibility/generation-rules`
- `GET /api/v1/recovery/generation-policies`
- `GET /api/v1/recovery/generation-policies/{failure_code}`
- `POST /api/v1/recovery/generation-requests`
- `GET /api/v1/recovery/generation-requests/{recovery_request_id}`
- `POST /api/v1/chat/interactions`
- `GET /api/v1/chat/interactions/{interaction_id}`
- `POST /api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs`
- `GET /api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/{repaired_response_handoff_id}`
- `POST /api/v1/chat/interactions/{interaction_id}/artifact-links`
- `GET /api/v1/chat/interactions/{interaction_id}/artifact-links`
- `POST /api/v1/retrieval/contexts`
- `GET /api/v1/retrieval/contexts/{retrieval_interaction_id}`
- `GET /api/v1/analytics/prompt-events/{prompt_event_id}`
- `GET /api/v1/analytics/users/{user_id}/task-profile`
- `GET /api/v1/analytics/users/{user_id}/recommendations`
- `GET /api/v1/prompts/bindings`
- `GET /api/v1/prompts/render-events/{prompt_render_event_id}`

Prompt registry seed:

- `ae.grounded_chat.default` records the grounded chat system prompt for debug
  and later prompt analytics lineage.

Workspace state:

- AE owns workspace state, default runtime controls, chat document identity, and
  activity summaries for the user-facing web shell.

Upload handoff:

- AE accepts upload metadata and mock `content_text`, forwards it to CX, and
  stores only safe CX document/job references. Source bytes, storage keys, and
  filesystem paths remain CX-owned.
- Slice 0196 adds canonical OA ownership propagation to this existing upload
  facade. AE now forwards `ownership_ref` with `oa.tenant`,
  `owner_subject_ref`, and `uploaded_by_subject_ref` while retaining legacy
  `tenant_id`, `owner_user_id`, and `user_id` aliases for compatibility.
- Slice 0197 completes the CX side of that handoff: CX now canonicalizes the
  propagated `ownership_ref` and rejects mismatched legacy aliases before
  owner-scoped duplicate detection runs.
- Slice 0199 can verify or ensure upload ownership refs with OA before CX is
  called. Set `NEX_AE_UPLOAD_OWNER_RESOLVER_MODE` to `verify` or `ensure` to
  enable the guardrail; the default `disabled` mode preserves mock-first local
  regression behavior.
- Upload handoff records keep the propagated stable subject refs for debugging,
  but do not store passwords, tokens, emails, raw identity profiles, source
  bytes, storage keys, or local filesystem paths.
- Slice 0277 adds `POST /api/v1/uploads/files` as the multipart browser-file
  facade. AE reads the request file only long enough to validate optional
  `source_sha256` and `size_bytes`, forwards bytes to CX as `content_base64`,
  and persists only the safe handoff metadata. CX remains the durable
  source-file system of record.
- Slice 0233 adds `nex_ae_api.auth_guard` as the reusable browser user-auth
  guard foundation. Browser user tokens are validated separately from
  service-to-service tokens, owner scope is claim-authoritative, and mismatched
  browser payload owner fields are rejected before downstream handoff wiring.
- Slice 0236 adds AE API auth session facade routes for AE Web. The login route
  issues a mock user token only into an HttpOnly same-site cookie and returns a
  safe `oa_browser_session.v1` snapshot. Current-session and logout routes
  validate either the Authorization header or that cookie and never return raw
  tokens, passwords, service credentials, provider endpoints, database URLs, or
  storage paths.
- Slice 0238 adds the shared facade-route auth boundary used by authenticated
  fetch-mode routes. Upload, document-library/detail, and retrieval facades now
  accept either service claims or browser user sessions; browser sessions derive
  owner/actor scope from claims and reject mismatched payload or stored scope.
- Slice 0239 updates the protected AE Web fetch-mode PostgreSQL smoke to call
  those facades with browser user auth, while preserving service-token auth for
  AE-to-CX handoff adapters.
- Slice 0240 closes the authenticated fetch-mode track with static guardrails
  that keep AE facade smoke calls browser-user authenticated and evidence
  claim-scope aware.
- Slice 0248 adds the AE-to-OA user-session client adapter. The adapter can call
  OA session issue, introspection, and revocation endpoints with service-token,
  trace, request-id, timeout, error mapping, and redaction-safe response
  handling. AE auth routes still default to the mock cookie mode until the
  facade wiring slice switches them to OA-backed opaque session ids.
- Slice 0249 wires an opt-in OA-backed auth session mode through
  `NEX_AE_AUTH_SESSION_MODE=oa`. In OA mode the browser cookie stores only the
  opaque OA session id, login delegates session issue to OA, current-session and
  route guard calls use OA introspection, and logout delegates revocation to OA
  before deleting the cookie. The default `mock` mode remains available for
  local regression.
- Slice 0250 adds protected PostgreSQL smoke evidence for that OA-backed AE
  auth mode. Set `NEX_AE_OA_AUTH_POSTGRES_SMOKE=1` with
  `NEX_AE_TEST_DATABASE_URL` and `NEX_OA_TEST_DATABASE_URL` to run the
  test-profile flow: OA membership seed, AE login/current/protected/logout,
  OA session revocation readback, AE marker readback, and cleanup.
- Slice 0255 extends the AE-to-OA auth client with
  `login_with_credentials(...)` for OA `POST /internal/v1/auth/user-login`.
  The adapter maps `employee_id` or `login_identifier` plus `password` to OA,
  propagates trace/request ids and the AE service token, and keeps submitted
  passwords out of returned errors/evidence. The public AE login facade is
  still switched in the next slice.
- Slice 0256 wires that credential-login adapter into
  `POST /api/v1/auth/session/login` when `NEX_AE_AUTH_SESSION_MODE=oa`.
  OA mode now accepts company `employee_id`/`login_identifier` plus `password`,
  delegates verification to OA, and stores only the returned opaque OA session
  id in the HttpOnly browser cookie. The default `mock` mode still rejects
  password fields and keeps the local regression login flow.
- Slice 0257 adds `scripts/smoke/run_ae_credential_login_postgres_smoke.py`
  as the dedicated protected smoke for that company credential-login path. Set
  `NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE=1` with the AE and OA test database
  URLs to verify credential seed, AE login, OA user-login, opaque cookie,
  revocation, PostgreSQL readback, cleanup, and redaction-safe evidence.
- Slice 0260 adds `scripts/smoke/run_ae_web_credential_login_postgres_smoke.py`
  as the AE Web-facing protected smoke. It reuses the real AE/OA PostgreSQL
  credential-login execution and adds web-surface plus route-guard evidence.

Document library:

- AE composes workspace document cards from upload handoffs and CX document,
  summary, and summary embedding status. Summary search is lexical and mock-only
  until a persistent AE read model is added.
- AE propagates the upload handoff owner scope (`tenant_id`, `owner_user_id`) as
  CX document detail query parameters before composing document cards. Invalid
  stored owner scope fails in AE with `ae.document_owner_scope_invalid` and does
  not call CX.
- Slice 0211 adds an AE document detail facade. It resolves the document through
  the stored upload handoff, calls the owner-scoped CX detail endpoint once, and
  returns an AE-safe projection that omits source bytes, markdown text, raw
  summaries, embedding vectors, storage keys, storage URIs, and local paths.
- Slice 0212 hardens that facade with
  `document_detail_projection.v1.schema.json`, valid/negative contract
  fixtures, and the `GET /api/v1/documents/{document_id}` OpenAPI response
  boundary.
- Slice 0213 freezes the near-term UI/read-model boundary: AE Web should read
  document detail through the AE facade, while `nex-ae-api` keeps only upload
  handoff and workspace-facing state. A persistent AE document detail read model
  remains deferred until latency, offline history, or UI aggregation needs make
  the duplication worth its synchronization cost.
- Slice 0214 adds protected PostgreSQL smoke evidence for the AE detail path.
  `NEX_AE_DOCUMENT_DETAIL_POSTGRES_SMOKE=1` runs the test-profile path:
  `AE /api/v1/uploads -> CX PostgreSQL upload -> AE /api/v1/documents/{id}
  -> CX PostgreSQL detail`.

Artifact handoff:

- AE creates pre-render handoff packages from CX generation and structured
  draft read APIs. Handoffs store safe lineage hashes, target formats,
  validation summaries, actor/workspace refs, and retention policy refs without
  copying raw prompts, source text, provider paths, or local storage paths.

Artifact records:

- AE creates user-facing artifact shells from validated handoffs. The record
  family fixes source refs, versions, render jobs, files, preview/download
  links, current version, status, and retention metadata while rendering remains
  a later slice.
- AE can synchronously render the first Markdown artifact version from a
  validated CX structured draft. Public artifact records expose version hashes
  and render job metadata, while Markdown content remains private until file and
  preview/download routes are added.
- AE materializes rendered Markdown as safe artifact file metadata with
  `ae://` storage refs and AE-owned preview/download routes. Public metadata
  never exposes local filesystem paths.

Prompt analytics:

- Chat interactions can record prompt event hashes, short previews, deterministic
  mock intent classifications, user task profiles, and early automation
  recommendation signals without storing full raw prompts.

Chat interactions can include a `retrieval` object. When enabled, AE asks CX for
a retrieval context package first, injects cited evidence into the CX generation
request, records a compact retrieval summary, and returns `NO_ANSWER` without
calling generation when CX has no supporting evidence.

Repaired response handoff:

- Slice 0379 adds the `ae_repaired_response_handoff.v1` contract foundation for
  presenting a CX remediation result back to the chat user. AE accepts only
  linked `cx_repaired_generation_lineage.v1` details and completed repaired
  generation records, then keeps response hash, short preview, usage metadata,
  quality summary, actor scope, links, and redaction flags.
- The handoff contract forbids raw prompt text, raw generation output, source
  text, evidence text, provider details, credentials, storage paths, and local
  filesystem paths. Runtime route and persistence wiring remain deferred.
- Slice 0381 freezes the runtime boundary before route/persistence wiring: AE
  API is the handoff system of record, AE Web owns the review surface, CX owns
  repaired lineage/source records, and AG owns remediation orchestration.
- Slice 0382 adds the AE-to-CX repaired response source client. It fetches CX
  remediation detail and the repaired generation record, validates schema
  versions, sanitizes source material into
  `ae_cx_repaired_response_source_package.v1`, and uses
  `NEX_AE_CX_REPAIRED_RESPONSE_TIMEOUT_SECONDS` for timeout tuning.
- Slice 0383 adds the repaired handoff store and PostgreSQL migration
  `ae_repaired_response_handoffs`. The table indexes owner/time,
  interaction/time, parent generation, repair generation, and remediation
  action while storing only sanitized handoff JSON fields.
- Slice 0384 wires the service API routes for creating and reading repaired
  response handoffs. POST fetches sanitized CX source material, builds the
  handoff record, and persists it; GET enforces interaction scope before
  returning the safe record.
- Slice 0385 adds protected PostgreSQL smoke evidence for the repaired handoff
  store. Set `NEX_AE_REPAIRED_RESPONSE_HANDOFF_POSTGRES_SMOKE=1` with
  `NEX_AE_TEST_DATABASE_URL` to run test-profile migration, insert/select/list
  checks, JSONB/index observations, and cleanup against the real AE test DB.
- Slice 0386 adds the AE Web-facing repaired response review projection. It
  converts a validated handoff into a redaction-safe review card with owner
  scope, generation refs, short repaired preview, lineage summary, primary
  user actions, and the future `/decisions` submit path.
- Slice 0387 adds the repaired response user decision contract and persistence
  foundation. Decisions record `accept_repair` or `keep_original`, selected and
  rejected CX generation ids, reason codes, comment hash/preview, actor scope,
  and redaction metadata in `ae_repaired_response_decisions`.

Chat artifact links:

- Chat records always include `artifact_refs`. AE can attach a rendered artifact
  ref to the originating interaction when chat document and interaction lineage
  match. The link stores safe artifact/version IDs, preview/download AE routes,
  quality badges, source lineage, and allowed actions without embedding rendered
  content or filesystem paths.

Generation recovery policies:

- AE reads the shared recovery policy catalog for retry, repair, regeneration,
  manual warning acceptance, and artifact render retry decisions. Policies store
  safe owner/action/lineage metadata and redaction-safe hashes only.
- AE can accept a user/operator recovery action for a failed CX generation
  record and store a separate safe recovery request envelope. The request fixes
  policy hash status, next attempt number, dispatch target, and retrieval reuse
  intent without mutating the failed chat or generation record.
