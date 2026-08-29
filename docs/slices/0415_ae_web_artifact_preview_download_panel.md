# Slice 0415: AE Web Artifact Preview Download Panel

Status: Implemented.

Wire artifact card preview/download anchors to a browser-safe side panel that
shows request state, compact metadata, and preview text without exposing
downloaded artifact body content.

## Scope

Slice 0415 adds:

- `src/artifactPreviewPanel.js` for preview/download route parsing, panel state,
  summaries, rendering metadata, and safety checks.
- `src/artifactMockRecord.js` for converting local chat artifact refs into
  artifact-client-compatible mock records.
- `main.js` click handling for `data-artifact-preview-route` and
  `data-artifact-download-route`.
- Mock artifact record synchronization so newly generated local artifact refs
  can be previewed/downloaded by the mock `artifactClient`.
- Artifact injection through authenticated runtime/session bootstrap so the
  browser registry has deterministic mock artifact data.
- HTML/CSS slots for feedback, summary, and preview content inside the Artifact
  panel.

Download actions intentionally render file metadata and a safe completion
message only. Downloaded artifact content remains available to the client
adapter result but is not copied into panel state, summaries, or diagnostics.

## Evidence

```bash
node --test apps/nex-ae-web/test/artifactPreviewPanel.test.mjs apps/nex-ae-web/test/artifactCard.test.mjs apps/nex-ae-web/test/artifactClient.test.mjs
```

```bash
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
```

```bash
npm --prefix apps/nex-ae-web test
```
