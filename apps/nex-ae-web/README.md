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

The browser shell is static and mock-first. Backend service calls are limited to
readiness checks until service-authenticated browser mediation is added.
