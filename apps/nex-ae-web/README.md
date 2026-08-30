# nex-ae-web

Korean-default NeX Agent Experience workspace shell.

Run locally:

```bash
npm --prefix apps/nex-ae-web run dev
```

The shell uses only Node.js standard library for serving static files and an
optional same-origin `/ae-api` dev proxy.

Slice 0045 integrates the first mock workspace surface and artifact card flow:

- Service readiness strip.
- Workspace summary metrics.
- Chat composer with retrieval and target format controls.
- Document scope list.
- Generation progress timeline.
- AE artifact handoff summary.
- AE artifact card refs with version, preview route, download route, and action
  metadata.
- AG audit summary.

Slice 0215 adds the AE document surface checkpoint:

- Safe document detail panel aligned to `ae_document_detail_projection.v1`.
- Selected document state with the AE facade route
  `/api/v1/documents/{document_id}`.
- Owner scope, CX source kind, extraction, summary, and confidence metadata
  surfaced without raw source, markdown, storage, summary text, or vector data.

Slice 0216 adds the document detail client adapter foundation:

- `src/documentDetailClient.js` owns mock and fetch client adapters.
- The static shell uses the mock adapter by default.
- The fetch adapter targets the AE facade route and uses same-origin browser
  credentials without embedding service tokens or provider secrets.
- Node built-in tests cover adapter success, not-found, HTTP failure, network
  failure, and invalid projection branches.

Slice 0217 adds the upload surface owner-scope checkpoint:

- `src/uploadSurface.js` owns the safe upload draft, ownership ref, and handoff
  payload preview shape.
- The workspace shows tenant, owner, uploaded-by, source hash, and
  `/api/v1/uploads` handoff route metadata.
- The browser surface does not include source content, service tokens, CX
  storage locations, provider URLs, or database details.

Slice 0218 adds document scope propagation:

- `src/documentScope.js` builds the selected document scope for retrieval.
- The chat mock flow passes selected document IDs into the AE retrieval
  interaction payload shape.
- The retrieval scope preview omits raw prompt text, source previews, chunks,
  provider URLs, and storage details.

Slice 0219 adds the upload client adapter foundation:

- `src/uploadClient.js` owns mock and fetch upload client adapters.
- The static shell submits the safe upload draft through the mock adapter by
  default.
- The fetch adapter targets `/api/v1/uploads` with same-origin browser
  credentials and JSON metadata only.
- Upload client previews omit raw source content, service tokens, CX storage
  locations, provider URLs, and database details.

Slice 0220 adds the retrieval context client adapter foundation:

- `src/retrievalClient.js` owns mock and fetch retrieval client adapters.
- Chat submit now passes the selected document-scope retrieval request through
  the mock adapter by default.
- The fetch adapter targets `/api/v1/retrieval/contexts` with same-origin
  browser credentials and JSON request metadata.
- Retrieval client previews omit raw prompts, source previews, chunk text,
  service tokens, provider URLs, and database details.

Slice 0221 adds the runtime client composition registry:

- `src/clientRegistry.js` composes document detail, upload, and retrieval
  clients from one runtime boundary.
- The static shell still defaults to mock mode.
- Fetch-mode composition is available behind the registry for later safe
  runtime config wiring.
- Registry summaries omit service tokens, provider URLs, database URLs, raw
  source content, and other server-only details.

Slice 0222 adds the safe runtime config loader:

- `src/runtimeConfig.js` reads the inline browser config and optional global
  override.
- The runtime config may choose `mock` or guarded `fetch` client mode and AE
  facade base URL.
- Fetch mode requires `features.fetch_clients_enabled = true`.
- Unsupported fields are rejected so credentials, provider endpoints, database
  endpoints, storage locations, and raw source material cannot enter browser
  runtime config.

Slice 0223 adds the fetch-mode static regression harness:

- `src/fetchModeHarness.js` runs document detail, upload, and retrieval fetch
  clients together with an injected fake fetch implementation.
- The harness requires injected fetch so regression tests do not accidentally
  use live network calls.
- Node tests assert AE facade route shapes and safe result summaries across all
  three fetch clients.

Slice 0224 adds the shared operation state model:

- `src/operationState.js` normalizes document detail, upload, and retrieval
  states as `idle`, `running`, `succeeded`, or `failed`.
- The workspace preview now includes safe operation summaries with attempts,
  retryability, route, client mode, and redaction metadata.
- Node tests cover operation transitions, invalid states, and safe metadata
  filtering.

Slice 0225 adds error and retry UX wiring:

- `src/operationFeedback.js` converts operation state into safe user feedback
  and retry-control metadata.
- Document detail, upload, and retrieval panels now expose retry buttons only
  when the underlying operation is retryable.
- Feedback text avoids raw error messages, prompts, source content, provider
  endpoints, database endpoints, and storage locations.

Slice 0226 adds the runtime diagnostics surface:

- `src/runtimeDiagnostics.js` summarizes runtime config, client registry, and
  operation states under `ae_web_runtime_diagnostics.v1`.
- The workspace now includes a runtime diagnostics panel with client mode,
  fetch flag, base path, operation counts, failed counts, and retryable counts.
- Diagnostics stay browser-safe and never include service tokens, provider
  endpoints, database endpoints, storage locations, raw prompts, or source text.

Slice 0227 adds the static browser smoke evidence runner:

- `scripts/smoke/run_ae_web_static_browser_smoke.py` starts the AE Web dev
  server, fetches the browser shell, and validates required static anchors.
- The full quality gate now runs the AE Web static browser smoke after contract
  validation.
- Python tests cover pass, missing-anchor, timeout, retry, process shutdown,
  and summary output branches.

Slice 0228 adds the protected fetch-mode smoke boundary:

- `scripts/smoke/run_ae_web_fetch_mode_protected_smoke_boundary.py` records the
  required env, phases, facade routes, and redaction rules for the next real
  AE Web fetch-mode smoke.
- The default quality gate runs this checker in skipped mode. It does not open
  network connections or PostgreSQL sessions unless the future execution smoke
  is explicitly enabled.
- The boundary requires future protected execution to use `nex_ae_test` and
  `nex_cx_test` readback evidence instead of a silent or metadata-only skip.

Slice 0229 adds the protected fetch-mode PostgreSQL smoke execution:

- `scripts/smoke/run_ae_web_fetch_mode_postgres_smoke.py` uses the Slice 0228
  boundary, then runs real test-profile migrations against AE and CX test DBs.
- The protected path writes and reads an AE API smoke marker, then exercises AE
  upload, document detail, and retrieval facade routes against a CX store backed
  by PostgreSQL.
- The default quality gate keeps this runner skipped until
  `NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE=1` and the test DB URLs are supplied.

Slice 0230 closes the fetch-mode evidence contract:

- `contracts/schemas/service/nex_ae_web/fetch_mode_smoke_evidence.v1.schema.json`
  freezes the PASS evidence shape for PostgreSQL readback, facade call counts,
  cleanup observations, and redaction checks.
- Positive and negative fixtures prove that redacted test DB URLs are allowed
  while raw database credentials are rejected.
- Regression tests validate the fixture contract and the smoke runner's
  generated PASS evidence shape.

Slice 0231 adds the authenticated runtime boundary audit:

- `src/authBoundary.js` defines the browser authentication boundary before live
  user-session wiring is added.
- Fetch mode is allowed only when the browser is authenticated, uses same-origin
  user credentials, and derives owner scope from session claims.
- The boundary keeps service tokens, provider details, database URLs, storage
  paths, and raw source material out of browser runtime config.

Slice 0234 adds the session client and login state model:

- `src/sessionClient.js` normalizes `oa_browser_session.v1` snapshots into the
  browser-safe `ae_web_session_state.v1` state.
- Mock and fetch adapters cover current session, login, and logout without
  storing raw user tokens, service credentials, passwords, provider endpoints,
  database URLs, or CX storage paths.
- The fetch adapter targets AE API auth facade routes with same-origin browser
  credentials.

Slice 0235 adds the authenticated runtime composition gate:

- `src/authenticatedRuntime.js` composes runtime config, session state, session
  client, auth boundary audit, and browser client registry in one envelope.
- Fetch-mode client composition is blocked unless the browser session is
  authenticated and owner scope is claim-derived.
- Runtime diagnostics now expose session state, auth boundary, and fetch-mode
  allowed status without leaking browser credentials or server-only endpoints.

Slice 0237 adds session bootstrap and login-state wiring:

- `src/sessionBootstrap.js` reads the current browser session through the
  session client and then recomposes the authenticated runtime.
- Fetch mode with no authenticated session falls back to mock browser clients
  while preserving blocked reasons in runtime diagnostics.
- Runtime diagnostics now include session bootstrap phase and active client
  mode, so anonymous, authenticated, blocked, and failed session reads are
  visible without exposing credentials.

Slice 0238 adds authenticated AE API fetch route-guard support:

- AE API upload, document, and retrieval facade routes accept browser user
  sessions in addition to existing service-token callers.
- Browser fetch-mode owner and actor scope is claim-derived; mismatched payload
  or stored scope is rejected by AE API before CX handoff.

Slice 0445 adds the artifact collection client adapter:

- `src/artifactClient.js` now includes `listArtifacts()` for mock and fetch
  clients.
- The fetch adapter targets `GET /api/v1/artifacts` with owner-scoped query
  parameters and same-origin browser credentials.
- Browser collection surfaces include metadata-only counts, formats, routes,
  owner scope, source summary, and quality summary without rendered payloads,
  download bytes, storage refs, database URLs, provider endpoints, or
  credentials.

Slice 0239 upgrades the protected PostgreSQL smoke:

- The smoke uses browser user auth for AE facade upload, document detail, and
  retrieval calls, while AE-to-CX calls remain service authenticated.
- PASS evidence records browser-user auth mode, claim owner authority, persisted
  retrieval evidence, and cleanup without exposing tokens or protected env
  values.

Slice 0240 closes the authenticated fetch-mode track:

- Static guardrails now verify the protected smoke remains browser-user
  authenticated and its PASS evidence keeps claim-scope checks.
- Real OA-backed login UI and browser automation remain deferred.

Slice 0258 adds the AE Web credential-login surface:

- `src/credentialLoginSurface.js` builds the company employee id plus password
  login payload expected by the AE auth facade.
- The workspace now includes a tenant, employee id, and password form, plus a
  logout control and safe login summary.
- The password is cleared after submit and is not stored in workspace state,
  runtime diagnostics, or browser-safe summaries.

Slice 0259 adds the authenticated session route guard:

- `src/sessionRouteGuard.js` summarizes protected AE facade routes as
  `allowed`, `blocked`, or `mock_preview`.
- Runtime diagnostics now include route guard status alongside session
  bootstrap and fetch-mode status.
- When a browser session becomes authenticated, upload and document owner scope
  is refreshed from OA session claims before protected route payloads are built.

Slice 0260 adds protected PostgreSQL smoke evidence:

- `scripts/smoke/run_ae_web_credential_login_postgres_smoke.py` verifies the AE
  Web credential-login surface against real AE and OA test databases.
- PASS evidence includes route guard `allowed`, credential count, revoked OA
  session readback, and safe web-surface checks.
- The runner is skipped by default in the quality gate unless explicitly
  enabled with test database URLs.

Slice 0261 adds the credential-login browser harness foundation:

- `src/credentialLoginHarness.js` runs current session, credential login,
  authenticated runtime composition, route guard, and logout through an injected
  fake fetch.
- The harness records browser request routes, methods, credential mode, and
  redaction status without using live network calls.
- Harness evidence fails if the raw password appears in the returned summary.

Slice 0262 adds the protected browser smoke boundary:

- `scripts/smoke/run_ae_web_credential_login_browser_smoke_boundary.py` records
  the required env, phases, browser routes, and redaction rules for a future
  credential-login browser smoke.
- The boundary is skipped by default in the quality gate and does not open
  network or PostgreSQL connections until explicitly enabled.
- Enabled execution must prove AE/OA test DB readiness, OA credential login, AE
  cookie session facade behavior, route guard `allowed`, logout readback, and
  redacted evidence.

Slice 0263 adds the deterministic browser harness smoke:

- `scripts/runCredentialLoginBrowserHarnessSmoke.mjs` executes the Slice 0261
  fake-fetch credential-login harness and emits
  `ae_web_credential_login_browser_harness_smoke.v1` evidence.
- `scripts/smoke/run_ae_web_credential_login_browser_harness_smoke.py` consumes
  the Slice 0262 boundary, runs the Node smoke, redacts protected env values,
  and reports a default quality-gate summary.
- `npm --prefix apps/nex-ae-web run smoke:credential-login-harness` runs the
  local AE Web smoke directly.

Slice 0264 adds protected execution readiness:

- `scripts/smoke/run_ae_web_credential_login_browser_execution_readiness.py`
  verifies that the browser boundary, harness smoke, AE Web anchors, package
  command, quality-gate wiring, and Node dependency are ready for protected
  execution.
- The readiness evidence records that any enabled credential-login browser
  smoke must connect to `NEX_AE_TEST_DATABASE_URL` and
  `NEX_OA_TEST_DATABASE_URL`.
- Playwright-style browser automation remains deferred until an explicit
  dependency decision; the next protected runner uses the existing FastAPI
  TestClient plus real PostgreSQL test databases.

Slice 0265 adds protected live smoke execution:

- `scripts/smoke/run_ae_web_credential_login_browser_live_smoke.py` combines
  the browser boundary, execution readiness, AE/OA credential-login PostgreSQL
  smoke, and deterministic browser harness evidence.
- When `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE=1`, the runner must connect
  to `NEX_AE_TEST_DATABASE_URL` and `NEX_OA_TEST_DATABASE_URL`; otherwise it is
  skipped by default in the quality gate.
- The browser smoke password is propagated into the server-side credential
  smoke while evidence remains redacted.

Slice 0266 hardens PostgreSQL evidence:

- `contracts/schemas/service/nex_ae_web/credential_login_browser_live_smoke_evidence.v1.schema.json`
  freezes the PASS evidence shape for the credential-login browser live smoke.
- `scripts/smoke/run_ae_web_credential_login_browser_postgres_evidence_hardening.py`
  calls the live smoke when enabled, validates the contract, and checks DB
  readback, migration, session revocation, cleanup, route guard, and redaction
  invariants.
- The hardening runner is skipped by default in the quality gate unless
  `NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE=1` is set.

Slice 0267 adds the operator profile:

- `docs/runbooks/ae_web_credential_login_browser_smoke.md` records the required
  env, command order, expected summaries, and redaction guardrails for protected
  credential-login browser smoke execution.
- `scripts/smoke/run_ae_web_credential_login_browser_operator_profile.py`
  validates the runbook, quality-gate wiring, profile value, and `*_test`
  database URL targeting without opening database connections.
- Operators should treat skipped live/hardening runners as not executed; the
  hardening runner is the final pass/fail signal when protected smoke is
  enabled.

Slice 0268 adds the same-origin runtime boundary:

- `scripts/serve.mjs` exports `createAeWebServer` and can proxy `/ae-api/*`
  requests to server-side `AE_API_PROXY_TARGET` when explicitly configured.
- Browser runtime config continues to use the safe same-origin `/ae-api` base
  path; the backend target URL stays out of browser config and evidence.
- `scripts/smoke/run_ae_web_same_origin_runtime_boundary.py` verifies the dev
  server, runtime config, session client, proxy regression test, runbook, and
  quality-gate wiring.

Slice 0269 adds the Playwright readiness foundation:

- `@playwright/test` is declared as an AE Web dev dependency with a local
  lockfile.
- `scripts/runCredentialLoginPlaywrightReadiness.mjs` verifies that Playwright
  is importable and can optionally run a Chromium launch check.
- `scripts/smoke/run_ae_web_playwright_readiness.py` keeps the default quality
  gate static, while `--require-installed` can execute the Node readiness
  script after npm dependencies are installed.
- `NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE` can point the launch check at a
  system Chrome/Chromium binary when Playwright browser downloads are not
  installed.

Slice 0270 adds protected Playwright PostgreSQL smoke execution:

- `scripts/runCredentialLoginPlaywrightSmoke.mjs` drives the actual browser DOM
  login/logout flow with Playwright through the same-origin `/ae-api` path.
- `scripts/smoke/run_ae_web_credential_login_playwright_postgres_smoke.py`
  starts AE API and AE Web on temporary local ports, seeds OA credentials in
  `nex_oa_test`, writes AE readback evidence in `nex_ae_test`, runs Playwright,
  verifies session revocation, and cleans up smoke rows.
- The runner is skipped by default unless
  `NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE=1` is set.

Slice 0271 audits the post-login document workflow:

- `scripts/smoke/run_ae_web_post_login_document_workflow_audit.py` verifies the
  upload, document detail, retrieval, client registry, AE API upload facade, and
  Playwright login smoke anchors before adding the authenticated upload flow.
- The audit records that Slice 0272-0274 should keep browser upload behavior on
  metadata handoff first, use same-origin `/ae-api`, derive owner scope from OA
  session claims, and reserve raw source bytes for a later explicit CX storage
  boundary.

Slice 0272 hardens the authenticated upload metadata surface:

- `src/uploadSurface.js` now exposes `ae_web_upload_file_metadata.v1` and builds
  upload drafts from browser file metadata without reading raw source bytes.
- The upload panel includes a file input and optional SHA-256 field. Selecting a
  file updates filename, content type, size, hash presence, owner scope, and the
  safe handoff preview.
- The preview records `sourceContentIncluded=false`, `localPathIncluded=false`,
  and keeps service tokens, provider endpoints, database URLs, and source bytes
  out of browser state.

Slice 0273 wires authenticated upload fetch:

- `src/authenticatedUploadWorkflow.js` composes fetch session and upload clients
  into a deterministic login -> owner-scope -> upload handoff -> logout flow.
- `scripts/runAuthenticatedUploadFetchSmoke.mjs` proves the same-origin
  `/ae-api` browser sequence with fake fetch and metadata-only upload payloads.
- `scripts/smoke/run_ae_web_authenticated_upload_fetch_smoke.py` exposes the
  smoke in the default quality gate while keeping live PostgreSQL execution for
  the protected Slice 0274 Playwright smoke.

Slice 0274 adds protected authenticated upload Playwright/PostgreSQL smoke:

- `scripts/runAuthenticatedUploadPlaywrightSmoke.mjs` drives login, browser file
  metadata, upload submit, and logout through `/ae-api`.
- `scripts/smoke/run_ae_web_authenticated_upload_playwright_postgres_smoke.py`
  runs AE/OA/CX migrations for test DBs, seeds OA credentials, starts AE API and
  AE Web, verifies CX persisted upload rows, checks OA session revocation, and
  cleans up smoke data.
- The runner is skipped unless
  `NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE=1` is set.

Slice 0278 wires browser FormData upload:

- `src/uploadSurface.js` exposes `/api/v1/uploads/files` and builds FormData
  payloads from selected files while keeping service tokens, provider endpoints,
  storage paths, and CX internal byte payload fields out of browser state.
- `src/uploadClient.js` keeps metadata-only JSON upload on `/api/v1/uploads`
  when no file object is supplied and switches to multipart FormData when
  `submitUploadDraft(draft, { file })` is called.
- The upload submit handler passes the selected file object from the file input
  to the upload client; AE remains a transient facade and CX remains the
  durable source-file owner.

Slice 0279 hardens the protected Playwright/PostgreSQL upload smoke:

- `scripts/runAuthenticatedUploadPlaywrightSmoke.mjs` now treats
  `/ae-api/api/v1/uploads/files` as the expected browser source-file route.
- Smoke evidence records multipart route/field booleans only; raw multipart
  bytes, credential material, service tokens, local paths, and provider
  endpoints stay out of evidence.
- `scripts/smoke/run_ae_web_authenticated_upload_playwright_postgres_smoke.py`
  requires real `test` profile DB URLs when enabled and verifies CX source-file
  checksum materialization before reporting `cx_checksum=verified`.

Slice 0316 adds the retrieval-quality warning surface:

- `src/retrievalQualityWarnings.js` maps
  `ae_chat_retrieval_quality_warning.v1` into a browser-safe
  `ae_web_retrieval_quality_warning_surface.v1` state.
- The retrieval panel and assistant messages can now show warning actions,
  warning kinds, and quality flag kinds without raw detail suffixes.
- Legacy retrieval `warnings`, `NO_ANSWER`, and unavailable states produce
  safe fallback warning surfaces while the chat runtime is being wired.

Slice 0317 adds default smoke evidence for that surface:

- `scripts/smoke/run_ae_web_retrieval_quality_warning_smoke.py` starts the AE
  Web dev server, checks the warning HTML anchors, checks production JS/CSS
  anchors, and rejects raw-detail leak fragments.
- The runner is part of the default quality gate and does not require live
  providers or PostgreSQL test DB access.

Slice 0319 adds the grounded response citation-quality surface:

- `src/groundedResponseQuality.js` maps
  `ae_chat_grounded_response_quality.v1` into a browser-safe
  `ae_web_grounded_response_quality_surface.v1` state.
- The chat pane and assistant messages can now show grounded citation boundary,
  citation status, issue count, and lineage-presence booleans.
- Raw output, evidence text, prompt text, provider details, local storage paths,
  and credential material stay out of browser summaries.

Slice 0320 adds default smoke evidence for that surface:

- `scripts/smoke/run_ae_web_grounded_response_quality_smoke.py` starts the AE
  Web dev server, checks grounded response quality HTML anchors, checks
  production JS/CSS anchors, and rejects raw-detail leak fragments.
- The runner is part of the default quality gate and does not require live
  providers or PostgreSQL test DB access.

Slice 0391 starts the repaired response review surface:

- `src/repairedResponseReviewBoundary.js` freezes chat interaction detail as
  the primary repaired response review surface.
- Document detail remains a secondary link/drill-down surface while repaired
  response decisions are submitted as `chat_review` actions.
- The boundary keeps raw prompts, raw generation output, raw source text,
  service tokens, provider endpoints, database endpoints, and storage locations
  out of browser state.

Slice 0392 adds the repaired response review client adapter:

- `src/repairedResponseReviewClient.js` owns mock and fetch adapters for the AE
  review projection list/detail routes.
- `src/clientRegistry.js` composes `repairedResponseReviewClient` in mock and
  fetch runtime modes.
- The adapter normalizes review projections into
  `ae_web_repaired_response_review_surface.v1` without storing raw prompts,
  raw generation output, source text, service credentials, provider endpoints,
  database endpoints, or storage locations.

Slice 0393 renders repaired response review cards in chat:

- `src/repairedResponseReviewCard.js` owns the safe card view-model, summary,
  and HTML rendering helper.
- `src/main.js` renders repaired response review cards on assistant messages
  using the same message-surface pattern as retrieval quality and generation
  feedback.
- Primary accept/keep buttons are visible but disabled until the decision
  submit adapter and click handling are wired in the following slices.

Slice 0394 adds the repaired response decision submit adapter:

- `src/repairedResponseDecisionClient.js` builds safe accept/keep decision
  requests from repaired response review surfaces.
- Mock and fetch clients submit to the existing AE API decision route with
  same-origin credentials in fetch mode.
- `src/clientRegistry.js` exposes `repairedResponseDecisionClient` for the
  following chat-card click wiring Slice.

Slice 0395 wires repaired response decision UX:

- `src/repairedResponseDecisionState.js` owns
  `READY_FOR_DECISION -> SUBMITTING -> RECORDED/FAILED` browser state.
- `src/main.js` routes review-card accept/keep clicks through
  `repairedResponseDecisionClient.submitRepairedResponseDecision`.
- `src/repairedResponseReviewCard.js` renders recorded decision IDs or failure
  statuses without exposing server-only details.

Slice 0396 adds protected PostgreSQL smoke evidence for repaired response
decisions:

- `scripts/smoke/run_ae_web_repaired_response_decision_postgres_smoke.py`
  checks AE Web decision wiring anchors before delegating to the persisted AE API
  decision smoke.
- The smoke is skipped by default and writes to `nex_ae_test` only when
  `NEX_AE_WEB_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE=1` is set.

Slice 0397 adds a repaired response review read-model:

- `src/repairedResponseReviewReadModel.js` derives safe browser counters and
  filters from repaired response review card summaries.
- The read-model supports `all`, `actionable`, `ready`, `submitting`,
  `recorded`, and `failed` filters without storing raw prompts, raw generation
  output, source text, service tokens, provider endpoints, database endpoints,
  or storage paths.

Slice 0398 wires repaired response review read-model diagnostics:

- `src/runtimeDiagnostics.js` accepts the safe read-model summary and reports
  total, actionable, and failed repaired response review counts.
- `src/main.js` derives those counters from current chat message review
  surfaces before rendering runtime diagnostics.

Slice 0399 adds protected PostgreSQL smoke evidence for repaired response review
diagnostics:

- `scripts/smoke/run_ae_web_repaired_response_review_diagnostics_postgres_smoke.py`
  checks the AE Web diagnostics/read-model anchors before delegating to the
  protected repaired response decision PostgreSQL smoke.
- The smoke is skipped by default and writes to `nex_ae_test` only when
  `NEX_AE_WEB_REPAIRED_RESPONSE_REVIEW_DIAGNOSTICS_POSTGRES_SMOKE=1` is set.

Slice 0400 closes S40:

- `scripts/smoke/run_s40_ae_web_repaired_response_review_closure.py` verifies
  that the repaired response review surface, client adapters, decision UX,
  read-model diagnostics, protected PostgreSQL smoke evidence, and slice docs
  remain registered together.

Slice 0411 audits the artifact browser surface before persisted wiring:

- `scripts/smoke/run_ae_web_artifact_surface_boundary_audit.py` freezes the
  current mock-first, inline-rendered artifact refs as the pre-S42 baseline.
- `nex-ae-web` remains the browser artifact surface owner while `nex-ae-api`
  remains the artifact system of record.
- The next browser work is ordered as artifact client adapter, safe card
  read-model, chat card renderer, and preview/download panel.
- Browser state and diagnostics must not expose raw prompts, source text,
  service tokens, provider endpoints, database endpoints, or storage paths.

Slice 0412 adds the artifact client adapter foundation:

- `src/artifactClient.js` owns mock and fetch adapters for AE artifact record,
  version, file metadata, preview, and download read paths.
- `src/clientRegistry.js` composes `artifactClient` beside document, upload,
  retrieval, feedback, and repaired-response clients.
- The adapter strips backend `storage_ref` metadata from browser surfaces and
  keeps registry summaries free of downloaded artifact content.
- Fetch mode uses same-origin browser credentials and AE facade routes only.

Slice 0413 adds the artifact card read-model:

- `src/artifactCardReadModel.js` converts chat artifact refs and optional
  persisted artifact client surfaces into `ae_web_artifact_card_read_model.v1`.
- The read-model normalizes preview, download, source, lineage, retry, warning,
  and collection summary state before any DOM rendering occurs.
- It accepts both AE API snake_case chat refs and browser camelCase artifact
  client surfaces.
- Summaries remain content-free and do not expose raw prompts, source text,
  service tokens, provider/database endpoints, storage refs, or storage paths.

Slice 0414 renders artifact cards in chat:

- `src/artifactCard.js` owns the safe HTML renderer for artifact card
  view-models.
- `src/main.js` now renders chat artifact refs through the read-model and
  renderer instead of building inline artifact link HTML.
- Artifact cards expose stable `data-artifact-*` anchors for preview,
  download, source, lineage, and future retry wiring.
- Card HTML escapes display text and continues to hide server-only fields and
  downloaded artifact content.

Slice 0415 wires artifact preview/download interactions:

- `src/artifactPreviewPanel.js` owns preview/download panel state, summaries,
  safe rendering metadata, and route parsing for
  `/api/v1/artifact-files/{artifact_file_id}/preview|download`.
- `src/artifactMockRecord.js` turns local chat artifact refs into deterministic
  mock records consumed by `artifactClient`.
- `src/main.js` handles artifact card preview/download clicks through
  `artifactClient`, updates `artifact_preview` operation state, and syncs mock
  artifact records when local chat artifacts change.
- The Artifact panel now shows request feedback, compact file/link metadata, and
  preview text; download actions show metadata only and do not render downloaded
  artifact content.

Slice 0416 adds the artifact versions/files panel:

- `src/artifactVersionPanel.js` builds browser-safe current version and file
  state without rendering raw hashes or storage locations.
- `src/main.js` refreshes artifact detail and version metadata through the
  active artifact client and records `artifact_versions` operation state.
- Runtime diagnostics include artifact preview and version operations without
  copying raw artifact bodies or backend-only metadata.

Slice 0417 adds deterministic artifact fetch-mode smoke:

- `scripts/runArtifactFetchModeSmoke.mjs` drives artifact detail, versions, file
  metadata, preview, and download adapters through an authenticated fake-fetch
  runtime.
- `npm run smoke:artifact-fetch` records same-origin route sequencing and
  verifies that browser fetch requests do not carry service-token headers.

Slice 0418 adds protected PostgreSQL smoke evidence:

- `scripts/smoke/run_ae_web_artifact_postgres_smoke.py` validates the web
  artifact surface and delegates persisted artifact read/write evidence to the
  AE artifact PostgreSQL smoke.
- The smoke is skipped by default and only touches `nex_ae_test` when explicitly
  enabled with the protected smoke flag and test database URL.

Slice 0419 adds protected artifact Playwright smoke coverage:

- `scripts/runArtifactPlaywrightSmoke.mjs` launches Chromium against the AE Web
  shell and drives artifact detail, versions, file metadata, preview, and
  download fetches through the same-origin `/ae-api` path.
- `scripts/smoke/run_ae_web_artifact_playwright_postgres_smoke.py` proves the
  persisted artifact flow against the test database before running the browser
  path.
- The smoke records only safe browser/panel summaries; raw download content,
  service tokens, database URLs, provider endpoints, and storage locations stay
  out of evidence.

Slice 0420 closes S42:

- `scripts/smoke/run_s42_ae_web_artifact_experience_closure.py` verifies that
  artifact browser boundary, client adapter, card renderer, preview/download
  panel, versions/files panel, fetch smoke, PostgreSQL smoke, Playwright smoke,
  docs, and quality-gate hooks remain registered together.

Slice 0421 starts S43 from the export/transform boundary:

- The browser format selector remains request-surface intent, not the
  multi-format materializer.
- AE Web may show `HTML_PREVIEW`, `DOCX`, and `PDF` choices, but AE API owns
  render job execution, artifact file metadata, preview/download links, and
  private rendered payload storage.
- Until S43 export adapters are wired, the live AE runtime remains
  Markdown-only while mock browser surfaces can still display future format
  metadata safely.

Slice 0426 wires export submit intent to the artifact client:

- `src/artifactClient.js` exposes `submitArtifactExportRequest` for mock and
  fetch clients. Fetch mode posts to
  `/api/v1/artifacts/{artifact_id}/render-jobs` with same-origin credentials,
  an `Idempotency-Key`, and explicit `target_formats`.
- `src/main.js` routes the composer format selector through
  `submitArtifactExportRequest` before rendering the chat artifact ref, while
  mock mode produces deterministic export evidence without requiring a live
  backend.
- `scripts/smoke/run_ae_artifact_export_postgres_smoke.py` is the protected
  test-database evidence point for multi-format export files.

Slice 0427 hardens binary artifact downloads:

- `src/artifactClient.js` separates text downloads from base64 binary downloads
  with `downloadPayloadKind`, `contentEncoding`, decoded `contentLength`, and
  `encodedContentLength`.
- Mock DOCX/PDF export downloads now use deterministic base64 payloads so
  browser regression can exercise the binary boundary without live network or
  PostgreSQL access.
- `src/artifactPreviewPanel.js` keeps download panels metadata-only. Raw text
  content and base64 payload bytes stay out of panel state, summaries, rendered
  HTML, and smoke evidence.

Slice 0428 hardens the fetch-mode export smoke:

- `scripts/runArtifactFetchModeSmoke.mjs` now covers same-origin export submit,
  safe request body observations, exported PDF file metadata readback, and PDF
  base64 download panel redaction in one deterministic fake-fetch run.
- The smoke remains live-network and PostgreSQL free. Protected persisted export
  evidence stays in the Slice 0426 test-database smoke.

Slice 0430 closes S43 from the browser side:

- `run_s43_ae_artifact_export_transform_closure.py` keeps the AE Web export
  submit adapter, binary download surface, fetch-mode export smoke, and panel
  redaction guard registered with the backend export/transform closure.

Slice 0431 audits the artifact delivery boundary:

- `run_ae_web_artifact_delivery_boundary_audit.py` freezes the S44 handoff
  between normalized artifact download surfaces and the future browser save
  adapter.
- `nex-ae-api` stays the download authorization owner, while `nex-ae-web`
  remains responsible for the browser delivery surface.
- Preview panels, runtime diagnostics, and smoke evidence stay metadata-only;
  raw text bodies and base64 payloads are only allowed inside the normalized
  download surface until the save adapter materializes them.

Slice 0432 adds the browser file-save adapter:

- `src/artifactDownloadSaveAdapter.js` is the only browser module allowed to
  materialize normalized text/base64 artifact downloads into Blob payloads.
- Save plans and save summaries stay metadata-only and redact raw text bodies,
  base64 bytes, storage refs, service credentials, database URLs, and provider
  endpoints.
- When browser download primitives are unavailable, the adapter still creates a
  safe `PREPARED` result so tests and non-browser harnesses can verify the
  boundary without writing files.

Slice 0433 wires download clicks to browser save:

- `src/main.js` now calls `saveArtifactDownload` after a successful
  `downloadArtifactFile` response and metadata-only panel update.
- The artifact preview/download operation keeps the visible panel status as
  `DOWNLOAD_READY` while recording the save result status as safe operation
  result metadata.
- Main download wiring remains free of raw download payload fields and
  server-only storage or credential material.

Slice 0434 adds the export result read-model:

- `src/artifactExportResultReadModel.js` summarizes export status,
  downloadable formats, render job metadata, and latest browser save status.
- The artifact panel renders the export result read-model as compact metadata
  beside the existing preview/download and version panels.
- Route strings, raw text bodies, base64 payloads, storage refs, credentials,
  database URLs, and provider endpoints remain out of the export result
  read-model and rendered HTML.

Slice 0435 hardens protected browser/PostgreSQL artifact delivery evidence:

- `scripts/runArtifactPlaywrightSmoke.mjs` now exercises the browser file-save
  adapter inside the Chromium page context with native `Blob` support and a
  fake document/URL harness, so smoke evidence proves save materialization
  without triggering host OS downloads.
- `scripts/smoke/run_ae_web_artifact_playwright_postgres_smoke.py` carries the
  browser save status and export result status into redacted protected evidence.
- The protected smoke remains opt-in with
  `NEX_AE_WEB_ARTIFACT_PLAYWRIGHT_POSTGRES_SMOKE=1` and must use
  `NEX_AE_TEST_DATABASE_URL` against the `nex_ae_test` database.

Slice 0436 consolidates artifact delivery action state:

- `src/artifactDeliveryActionState.js` now owns preview/download running,
  success, failure, retry, panel, and browser save result transitions.
- `src/main.js` delegates artifact file action state changes to that module, so
  the UI shell stays focused on event wiring and rendering.
- Delivery action summaries preserve retry/error status while excluding raw
  error messages, download payloads, storage refs, credentials, database URLs,
  and provider endpoints.

Slice 0437 adds a download format selector:

- `src/artifactDownloadFormatSelector.js` builds browser-safe MD/DOCX/PDF
  option state from artifact refs and validates enabled routes with the
  artifact-file download route parser.
- The artifact summary renders compact download format controls and routes
  clicks through the same `submitArtifactDownloadAction` path used by artifact
  cards.
- Selector summaries keep route and payload details out of diagnostics while
  rendered action controls carry only same-origin artifact download routes.

Slice 0438 adds artifact delivery accessibility smoke evidence:

- `scripts/runArtifactDeliveryAccessibilitySmoke.mjs` renders artifact cards and
  download format selectors through real browser-side modules, then checks
  keyboard-reachable preview/download anchors, selected state, disabled format
  state, same-origin routes, focus-visible styling, and redaction.
- The smoke is deterministic and PostgreSQL-free; protected persisted browser
  evidence stays in the Playwright/PostgreSQL smoke path.

Slice 0439 adds protected multi-format artifact delivery evidence:

- `scripts/smoke/run_ae_web_artifact_multiformat_playwright_postgres_smoke.py`
  prepares a real `MD/HTML_PREVIEW/DOCX/PDF` artifact in `nex_ae_test`, serves
  AE API and AE Web locally, and verifies the browser download selector through
  Playwright.
- The browser still previews/downloads the MD file for safe text inspection,
  while the selector and version panel must show four persisted downloadable
  formats.
- The smoke is skipped by default and only runs when
  `NEX_AE_WEB_ARTIFACT_MULTIFORMAT_PLAYWRIGHT_POSTGRES_SMOKE=1` is explicitly
  set with `NEX_AE_TEST_DATABASE_URL`.

Slice 0440 closes S44:

- `scripts/smoke/run_s44_ae_web_artifact_delivery_closure.py` checks that the
  delivery boundary audit, file-save adapter, action-state module, export result
  read-model, download format selector, accessibility smoke, and protected
  PostgreSQL/Playwright smokes remain connected.
- S44 now treats multi-format artifact export from S43 as an input contract and
  AE Web artifact delivery as a metadata-safe browser surface.

Slice 0441 starts S45:

- The artifact library/management boundary is frozen before collection APIs and
  browser library panels are added.
- AE Web owns the browser library surface, but it must keep using AE API route
  metadata and metadata-only read-models without rendered payloads, storage
  paths, database URLs, or provider secrets.
- Slice 0442 adds the AE API collection read-model foundation that the future
  browser library panel will consume after route/client wiring.
- Slice 0443 exposes the authenticated AE API collection route. AE Web client
  wiring remains deferred, but the browser library now has a stable API target:
  `GET /api/v1/artifacts`.

The browser shell is static and mock-first. Backend service calls are limited to
authenticated fetch-mode clients and readiness checks.
