# Slice 0416: AE Web Artifact Versions Files Panel

Status: Implemented.

Add a browser-safe artifact versions/files panel so AE Web can show rendered
artifact lineage and file availability without rendering storage paths, service
tokens, database URLs, or raw hash values.

## Scope

Slice 0416 adds:

- `src/artifactVersionPanel.js` for artifact/version/file read-model state,
  summaries, rendering, error states, and safety checks.
- `artifact_versions` operation tracking in AE Web runtime diagnostics.
- Runtime wiring that refreshes artifact detail and version metadata through
  the active artifact client, using mock clients in local regression and fetch
  clients when authenticated fetch mode is enabled.
- Artifact panel DOM/CSS slots for compact versions/files feedback, summary,
  and current-version file rows.

The panel reports hash and action availability as counts/flags only. It does
not expose physical storage locations, raw artifact body content, provider
endpoints, or database connection details.

## Evidence

```bash
node --test apps/nex-ae-web/test/artifactVersionPanel.test.mjs apps/nex-ae-web/test/artifactPreviewPanel.test.mjs apps/nex-ae-web/test/artifactClient.test.mjs
```

```bash
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
```

```bash
npm --prefix apps/nex-ae-web test
```
