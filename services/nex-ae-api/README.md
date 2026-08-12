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
