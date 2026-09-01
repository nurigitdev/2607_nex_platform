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
- `GET /api/v1/artifact-retention/candidates`
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
- Slice 0401 freezes the runtime persistence/storage boundary before durable
  artifact work. Current artifact records, render jobs, files, links, and
  rendered Markdown payloads are process-local memory; the next S41 slices move
  metadata to `nex_ae` PostgreSQL and payloads behind
  `NEX_AE_ARTIFACT_STORAGE_ROOT`.
- Slice 0402 adds the AE artifact PostgreSQL schema foundation. Durable metadata
  is split across handoffs, artifacts, source refs, versions, render jobs,
  files, and links with owner/workspace/time indexes. The schema stores only
  safe metadata and logical `ae://` refs; rendered payload bytes remain outside
  the database.
- Slice 0403 adds `SqlAlchemyArtifactHandoffStore` and
  `SqlAlchemyArtifactRecordStore` with SQLite regression coverage. The adapters
  round-trip the same record family shape as the in-memory stores; default API
  wiring and durable rendered payload storage remain deferred.
- Slice 0404 adds the rendered artifact storage adapter boundary. The default
  mock path can remain in memory, while `NEX_AE_ARTIFACT_STORAGE_ROOT` enables
  private local Markdown payload storage behind logical `ae://artifacts/...`
  refs. Local paths stay out of API records and evidence.
- Slice 0405 wires artifact routes to SQLAlchemy stores when
  `app.state.nex_persistence.api_session_factory` is attached. Explicit test
  stores still override defaults, and the public API shape is unchanged across
  in-memory and persisted modes.
- Slice 0421 audits the export/transform boundary before S43 multi-format
  rendering begins. Contracts and AE Web already name `HTML_PREVIEW`, `DOCX`,
  and `PDF`, but the current AE runtime intentionally materializes only `MD`
  through the Markdown renderer. S43 should add export/transform adapters behind
  the existing AE render job, artifact file, link, and private payload storage
  boundary instead of moving conversion responsibility to CX or the browser.
- Slice 0422 adds the AE export/transform catalog and format-neutral rendered
  payload storage contract. `ARTIFACT_TRANSFORMER_CATALOG` now centralizes
  target format, MIME type, extension, render stage, content kind, and current
  implementation state for `MD`, `HTML_PREVIEW`, `DOCX`, and `PDF`.
  Rendered payload storage now supports typed bytes through
  `save_rendered_artifact_file(...)` and `get_rendered_artifact_file(...)`
  while keeping the older Markdown helper methods as compatibility wrappers.
- Slice 0423 implements the AE-owned `HTML_PREVIEW` materializer. Render jobs
  can now request `MD` and `HTML_PREVIEW` together; AE stores each payload
  privately, emits separate file/link metadata, and decodes only text formats
  for preview/download JSON responses. `DOCX` and `PDF` remain cataloged but
  intentionally rejected until their export adapters are implemented.
- Slice 0424 implements the AE-owned `DOCX` export adapter using `python-docx`.
  Render jobs can now request `DOCX` when the handoff allowed it. AE stores the
  generated DOCX bytes privately, emits deterministic `.docx` file metadata,
  keeps preview unavailable for binary files, and returns base64 content from
  the existing download JSON boundary. `PDF` remains cataloged but deferred.
- Slice 0425 implements a deterministic text `PDF` export adapter and freezes
  `MULTI_FORMAT_RENDER_STAGE_ORDER`. Render policy hashes now include the
  canonical stage sequence for the requested format set. PDF bytes stay in
  private rendered storage, previews remain unavailable for binary files, and
  downloads use the same base64 JSON boundary introduced for DOCX. Rich layout
  and embedded Korean fonts are deferred to a later export quality slice.
- Slice 0426 adds protected multi-format export smoke evidence for the AE test
  database. Set `NEX_AE_ARTIFACT_EXPORT_POSTGRES_SMOKE=1` with
  `NEX_AE_TEST_DATABASE_URL` to run test-profile migration, handoff/create/render
  route checks, persisted version/file/link selects, text/base64 download shape
  checks, local rendered payload verification, and cleanup against the real
  `nex_ae_test` database.
- Slice 0427 updates the AE Web download surface for S43 binary exports. The AE
  API download contract remains unchanged: text formats return inline text, and
  DOCX/PDF return base64 content through the protected download boundary. AE Web
  now keeps only binary metadata in panel and evidence surfaces.
- Slice 0429 hardens the protected multi-format export PostgreSQL smoke with
  artifact detail, versions, and render-job readbacks. The smoke summary reports
  `read_model_files=4` when the persisted rows, download links, and service
  read-model routes agree after rendering.
- Slice 0430 closes S43 with
  `run_s43_ae_artifact_export_transform_closure.py`, a quality-gate closure
  checkpoint covering the export boundary audit, transform catalog, HTML/DOCX/PDF
  adapters, AE Web export submit and binary download surfaces, fetch-mode smoke,
  and protected PostgreSQL read-model smoke.

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
- Slice 0388 wires repaired response decisions into AE API routes. The handoff
  path now supports decision POST/list/detail operations, enforces service-token
  authorization and interaction scope, and returns problem responses for missing
  handoffs, invalid payloads, and missing decisions.
- Slice 0389 adds protected PostgreSQL smoke evidence for repaired response
  decisions. Set `NEX_AE_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE=1` with
  `NEX_AE_TEST_DATABASE_URL` to run test-profile migration, DB-backed route
  POST/list/detail checks, JSONB/index observations, and cleanup against the
  real AE test DB.
- Slice 0390 closes S39 with a repaired response handoff closure checkpoint and
  adds AE OpenAPI coverage for repaired response decision POST/list/detail.
- Slice 0392 exposes read-only repaired response review projection routes for
  AE Web. The handoff review collection and detail routes return
  `ae_repaired_response_review_collection.v1` and
  `ae_repaired_response_review_projection.v1` without adding new persistence.

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

Artifact library management:

- Slice 0441 starts S45 by freezing the artifact library boundary before list
  APIs are added. AE API remains the artifact system of record, collection
  scope is tenant/workspace/owner, and future list responses must stay
  metadata-only without rendered payloads, storage roots, provider secrets, or
  database URLs.
- Slice 0442 adds the service-side artifact collection read-model. In-memory
  and SQLAlchemy stores can list artifact summaries by tenant/workspace/owner,
  optionally filter by status, and return bounded metadata-only collection
  items before the API route is exposed.
- Slice 0443 exposes `GET /api/v1/artifacts` for authenticated collection
  queries. The route requires tenant/workspace/owner scope, accepts optional
  status and limit filters, and returns the same metadata-only read-model used
  by the stores.
- Slice 0444 adds protected PostgreSQL smoke evidence for the collection route.
  When explicitly enabled against `nex_ae_test`, it migrates the real test DB,
  creates owner-scoped artifacts, verifies list/status/limit behavior, checks
  collection indexes, and cleans up inserted rows.
- Slice 0450 closes S45 by checking the AE collection read-model, API route,
  PostgreSQL smoke evidence, AE Web library surface, and AG operations
  projection remain connected as metadata-only artifact library contracts.
- Slice 0451 starts S46 by freezing artifact lifecycle management before
  mutation contracts are added. AE API remains the lifecycle system of record,
  the first allowed actions are reversible metadata actions (`ARCHIVE`,
  `RESTORE`, `MARK_DELETED`), and physical file deletion/storage purge remains
  deferred to a later retention or purge track.
- Slice 0452 adds the lifecycle command/result contract foundation. The action
  helpers normalize lifecycle commands, reject invalid transitions, hash raw
  comments instead of carrying comment text, and return metadata-only results
  under `ae_artifact_lifecycle_action.v1` and
  `ae_artifact_lifecycle_action_result.v1`.
- Slice 0453 wires lifecycle commands into the AE artifact stores and
  `POST /api/v1/artifacts/{artifact_id}/lifecycle-actions`. The route is
  authenticated, applies only metadata status transitions, rejects stale status
  commands, and returns the lifecycle result contract without deleting rendered
  files or exposing raw comments/storage material.
- Slice 0454 adds protected PostgreSQL smoke evidence for lifecycle actions.
  Set `NEX_AE_ARTIFACT_LIFECYCLE_POSTGRES_SMOKE=1` with
  `NEX_AE_TEST_DATABASE_URL` to migrate the real AE test DB, create a rendered
  artifact, execute archive/restore/logical-delete through the API, verify
  direct DB status/file/link rows, and clean up smoke records.
- Slice 0460 closes S46 by checking the AE lifecycle contract, repository/API
  wiring, PostgreSQL smoke evidence, AE Web lifecycle surface, and AG read-only
  lifecycle projection remain connected without adding physical deletion.
- Slice 0461 starts S47 by freezing the artifact retention/purge boundary.
  `artifact_status=DELETED` is the first logical purge flag, candidate scans are
  dry-run and metadata-only through Slice 0465, the default post-logical-purge
  retention window is 30 days with 15-day and 30-day presets, and physical file
  deletion remains deferred to a guarded scheduled batch track.
- Slice 0462 adds the `ae_artifact_retention_policy.v1` contract and runtime
  policy helpers. The contract keeps logical purge first, requires dry-run
  candidate scans, disables physical file and database-row deletion, and fixes
  the first scheduled batch window at 02:00-05:00 `Asia/Seoul`.
- Slice 0463 adds the artifact retention candidate read-model behind the
  existing in-memory and SQLAlchemy artifact stores. Candidate scans are
  owner-scoped, dry-run only, ordered oldest-first, and currently treat
  `updated_at` on `DELETED` artifacts as the logical purge timestamp.
- Slice 0464 exposes that read-model through
  `GET /api/v1/artifact-retention/candidates`. The route is authenticated,
  read-only, owner-scoped, dry-run only, and returns metadata without rendered
  payloads, storage refs, database URLs, source text, or local paths.
- Slice 0465 adds protected PostgreSQL smoke evidence for retention candidates.
  Set `NEX_AE_ARTIFACT_RETENTION_CANDIDATE_POSTGRES_SMOKE=1` with
  `NEX_AE_TEST_DATABASE_URL` to migrate the real AE test DB, create two
  rendered artifacts, mark both `DELETED`, age one beyond the 30-day cutoff,
  verify API and direct DB candidate counts, confirm local files/DB rows remain
  retained, and clean up smoke rows.
- Slice 0466 adds the `ae_artifact_retention_execution.v1` contract and runtime
  helpers. Retention execution remains guarded: dry-run cannot enable delete
  flags, successful execute requires database and storage mutation flags, and
  the scheduled batch window stays 02:00-05:00 `Asia/Seoul`.
- Slice 0467 wires guarded retention purge into the AE artifact stores without
  exposing an HTTP route yet. Dry-run remains the default, execute is blocked
  unless all delete flags are enabled, artifact graph rows are deleted
  child-first, rendered files are removed through the storage adapter, and
  handoff lineage records are retained.
- Slice 0468 exposes the guarded purge path as
  `POST /api/v1/artifact-retention/purge`. The route is authenticated, defaults
  to dry-run, rejects non-boolean control flags and dry-run delete flags, and
  returns metadata-only `ae_artifact_retention_execution.v1` evidence.
- Slice 0469 adds protected PostgreSQL smoke evidence for the purge route. When
  `NEX_AE_ARTIFACT_RETENTION_PURGE_POSTGRES_SMOKE=1` is set against
  `NEX_AE_TEST_DATABASE_URL`, the runner migrates the real AE test DB, creates
  rendered logical-purge artifacts, verifies dry-run and blocked execute retain
  rows/files, executes guarded purge, checks direct DB row counts and local
  storage file counts, then cleans up smoke data.
- Slice 0470 closes S47 by checking the retention boundary audit, policy and
  execution contracts, candidate read-model/API, guarded purge store/API,
  PostgreSQL smoke evidence, quality gate hooks, and metadata-only redaction
  posture remain connected end to end.
- Slice 0471 starts S48 by freezing the artifact retention execution history
  boundary before adding persistence. `nex-ae-api` remains the system of record,
  `ae_artifact_retention_executions` is the planned history table, purge
  executions stay metadata-only, and idempotency is scoped by tenant, workspace,
  owner, and idempotency key.
- Slice 0472 adds the PostgreSQL migration for
  `ae_artifact_retention_executions`. It records flat query fields, the
  validated execution payload, a payload hash, scope/idempotency indexes, and
  safety constraints while avoiding raw content, local storage paths, and
  foreign keys to records that may be physically purged.
- Slice 0473 adds the retention execution history repository layer. History
  records are derived from validated purge execution evidence, hashed, saved via
  in-memory or SQLAlchemy stores, and reused by tenant/workspace/owner-scoped
  idempotency keys before API wiring.
- Slice 0474 wires `POST /api/v1/artifact-retention/purge` to the retention
  history store. The route reuses persisted idempotency history for duplicate
  commands, saves dry-run/blocked/succeeded execution evidence, and checks
  history store availability before guarded physical delete.
- Slice 0475 adds protected PostgreSQL smoke evidence for retention execution
  history. When `NEX_AE_ARTIFACT_RETENTION_HISTORY_POSTGRES_SMOKE=1` is set
  against `NEX_AE_TEST_DATABASE_URL`, the runner migrates the test DB, exercises
  dry-run/blocked/guarded execute plus idempotency replay, directly verifies
  `ae_artifact_retention_executions`, and cleans up generated rows.
- Slice 0476 adds the retention execution history read-model contract. Stores
  still return persisted history records, while list surfaces wrap them as
  metadata-only collection/items with summary counts and execution payload
  hashes instead of raw execution JSON.
- Slice 0477 exposes `GET /api/v1/artifact-retention/executions` for
  authenticated retention history queries. The route requires tenant,
  workspace, and owner scope, accepts mode/status/limit filters, and returns the
  Slice 0476 metadata-only collection rather than persisted raw execution
  records.
- Slice 0478 adds protected PostgreSQL smoke evidence for the retention history
  query route. When
  `NEX_AE_ARTIFACT_RETENTION_HISTORY_QUERY_POSTGRES_SMOKE=1` is set against
  `NEX_AE_TEST_DATABASE_URL`, the runner migrates the test DB, seeds history
  rows, queries all/execute/blocked collections through the API, cross-checks DB
  counts, and cleans up the generated history rows without exposing raw
  execution JSON.
- Slice 0480 closes S48 by checking retention history boundary, migration,
  repository, purge writer, read-model, query API, PostgreSQL writer/query smoke
  evidence, AG projection linkage, and metadata-only redaction posture remain
  connected end to end.
- Slice 0481 starts S49 by freezing the scheduled artifact retention operations
  boundary. AE remains the retention system of record, scheduled runs default to
  dry-run in the 02:00-05:00 `Asia/Seoul` window, execute-mode deletion keeps
  the three existing guard flags, and scheduler/worker mutation remains deferred.
- Slice 0482 adds `ae_artifact_retention_schedule.v1`, a metadata-only schedule
  contract with schedule daemon disabled, planning enabled, default `DRY_RUN`,
  15/30-day presets, max delete limits, three execute guard flags, and AG
  dispatch-only ownership semantics.
- Slice 0483 adds the retention batch plan read-model. Artifact stores can now
  produce metadata-only READY/NOOP plans from retention candidates, cap selected
  artifacts by `max_delete_count`, estimate child-row/file deletes, and keep all
  scheduler, storage, database, and history mutations disabled.
- Slice 0484 exposes the read-model as
  `GET /api/v1/artifact-retention/batch-plan`. The route is authenticated,
  accepts scoped retention planning filters plus `Idempotency-Key`, returns
  READY/NOOP metadata-only plan evidence, and does not mutate artifacts,
  rendered storage, or retention history.
- Slice 0485 adds protected PostgreSQL smoke evidence for the batch plan route.
  Set `NEX_AE_ARTIFACT_RETENTION_BATCH_PLAN_POSTGRES_SMOKE=1` with
  `NEX_AE_TEST_DATABASE_URL` to migrate the real AE test DB, create three
  rendered logical-purge artifacts, verify `candidate_count=2` and
  `selected_count=1` through the route plus direct DB counts, confirm rows/files
  remain retained, and clean up smoke rows.
- Slice 0486 adds
  `ae_artifact_retention_scheduled_execution_command.v1`. It turns a batch plan
  into a deterministic metadata-only command envelope for scheduler ticks,
  mock workers, and AG dispatch. READY commands carry only a dry-run purge
  request with delete, storage, and database-row mutation flags false; NOOP
  commands carry no execution request.
- Slice 0487 adds a mock scheduled execution worker pipeline. The helper
  validates the scheduled command, forces the existing purge path into
  `DRY_RUN`, optionally writes retention execution history, leaves artifact
  rows/rendered storage untouched, and returns worker result evidence without
  embedding the full command payload.
- Slice 0489 adds protected PostgreSQL smoke evidence for scheduled execution.
  Set `NEX_AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_POSTGRES_SMOKE=1` with
  `NEX_AE_TEST_DATABASE_URL` to migrate the real AE test DB, create rendered
  logical-purge artifacts, build a batch plan and scheduled command, run the
  mock worker through SQLAlchemy artifact/history stores, verify persisted
  history, verify artifact/storage rows remain retained, project the plan
  through AG's metadata-only operator view, and clean up smoke rows.
- Slice 0490 closes S49 by checking the scheduled retention boundary, schedule
  contract, batch plan read-model/API, PostgreSQL smoke evidence, scheduled
  command, mock worker, AG projection linkage, and dry-run/metadata-only
  redaction posture remain connected end to end.
- Slice 0491 starts S50 by freezing the scheduler runtime boundary. AE scheduled
  retention uses `common_job.v1` and the shared worker runner, keeps scheduler
  daemon startup and physical delete automation deferred, and limits the first
  runtime path to dry-run scheduled execution with persisted history.
- Slice 0492 adds `ae_artifact_retention_scheduled_job.v1`. READY scheduled
  execution commands can now be wrapped as retryable `common_job.v1` envelopes
  with metadata-only payloads, deterministic job IDs/idempotency, AE API links,
  and redaction flags that keep raw content, storage locators, DB URLs, and
  provider secrets out of the queue contract.
- Slice 0493 adds scheduled job admission around the Slice 0492 contract. READY
  batch plans become deterministic enqueue-ready jobs, duplicate submissions
  reuse the shared JobQueue idempotency key, and NOOP plans are returned as
  skipped admissions without touching the queue, scheduler daemon, worker, or
  physical delete automation.
- Slice 0494 adds the scheduled retention worker runner adapter. The shared
  worker runner now claims `ae.artifact_retention.scheduled_execution` jobs,
  invokes the existing dry-run mock worker, writes optional retention history,
  updates worker heartbeats, and lets the shared JobQueue complete or retry jobs
  without enabling physical delete automation.
- Slice 0495 adds protected PostgreSQL evidence for that runtime path. When
  explicitly enabled against `NEX_AE_TEST_DATABASE_URL`, it migrates the real AE
  test DB, enqueues a scheduled retention job, runs the shared worker once, and
  directly checks `service_jobs`, `service_worker_heartbeats`, and retention
  history before cleanup.
- Slice 0498 exposes the scheduled retention runtime through protected,
  metadata-only AE API routes: scheduler config, scheduled job list, and
  scheduled job admission. Admission uses the shared JobQueue from AE
  persistence, keeps the scheduler daemon disabled, and preserves the
  AE-only enqueue boundary for AG dispatch requests.
- Slice 0499 adds protected AE/AG PostgreSQL smoke evidence for that boundary.
  When explicitly enabled against `NEX_AE_TEST_DATABASE_URL`, it migrates the
  real AE test DB, lets AG dispatch through the AE scheduled-job admission API,
  directly verifies the persisted `service_jobs` QUEUED row, lists it back via
  AG's scheduled-job projection, and cleans up smoke artifacts and jobs.
- Slice 0500 closes S50 by checking the scheduler runtime boundary, scheduled
  job contract, admission, shared worker runner, AE scheduler/read-model APIs,
  AG scheduled job/dispatch projections, PostgreSQL smoke evidence, and
  metadata-only redaction posture remain connected end to end.
