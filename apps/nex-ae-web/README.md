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

The browser shell is static and mock-first. Backend service calls are limited to
readiness checks until service-authenticated browser mediation is added.
