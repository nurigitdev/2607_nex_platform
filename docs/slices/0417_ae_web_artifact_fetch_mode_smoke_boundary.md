# Slice 0417: AE Web Artifact Fetch Mode Smoke Boundary

Status: Implemented.

Add a deterministic AE Web artifact fetch-mode smoke runner that exercises the
artifact detail, versions, file metadata, preview, and download adapters through
an authenticated browser runtime without using live network or PostgreSQL.

## Scope

Slice 0417 adds:

- `apps/nex-ae-web/scripts/runArtifactFetchModeSmoke.mjs` for fake-fetch
  artifact adapter evidence.
- `apps/nex-ae-web/test/artifactFetchModeSmoke.test.mjs` for same-origin route
  sequencing, fetch runtime authorization, CLI output, and redaction checks.
- `npm --prefix apps/nex-ae-web run smoke:artifact-fetch` as the local smoke
  alias.

The runner deliberately feeds server-side artifact fields such as storage refs
and download content into fake API responses, then proves the browser evidence
keeps only safe summaries and panel metadata.

## Evidence

```bash
node --test apps/nex-ae-web/test/artifactFetchModeSmoke.test.mjs apps/nex-ae-web/test/artifactVersionPanel.test.mjs apps/nex-ae-web/test/artifactPreviewPanel.test.mjs apps/nex-ae-web/test/artifactClient.test.mjs
```

```bash
npm --prefix apps/nex-ae-web run smoke:artifact-fetch
```

```bash
npm --prefix apps/nex-ae-web test
```
