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

The browser shell is static and mock-first. Backend service calls are limited to
readiness checks until service-authenticated browser mediation is added.
