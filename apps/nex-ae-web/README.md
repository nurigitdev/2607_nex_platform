# nex-ae-web

Korean-default NeX Agent Experience workspace shell.

Run locally:

```bash
npm --prefix apps/nex-ae-web run dev
```

The shell uses only Node.js standard library for serving static files.

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

The browser shell is static and mock-first. Backend service calls are limited to
authenticated fetch-mode clients and readiness checks.
