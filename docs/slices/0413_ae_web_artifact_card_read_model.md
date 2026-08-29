# Slice 0413: AE Web Artifact Card Read-Model

Status: Implemented.

Add a browser-safe read-model for chat artifact cards before rendering the new
artifact card UI.

## Scope

Slice 0413 adds `src/artifactCardReadModel.js`:

- Normalizes snake_case chat artifact refs and camelCase artifact client
  surfaces into `ae_web_artifact_card_read_model.v1`.
- Derives preview, download, source, lineage, retry, and warning action state.
- Supports collection summaries for chat messages with multiple artifact refs.
- Keeps summaries free of downloaded artifact content and server-only metadata.

## Evidence

```bash
node --test apps/nex-ae-web/test/artifactCardReadModel.test.mjs apps/nex-ae-web/test/artifactClient.test.mjs
```

```bash
npm --prefix apps/nex-ae-web test
```
