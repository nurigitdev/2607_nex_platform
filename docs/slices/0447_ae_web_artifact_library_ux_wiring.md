# Slice 0447: AE Web Artifact Library UX Wiring

## Intent

Wire the S45 artifact collection and library read-model into the AE Web shell so
users can see an owner-scoped artifact library, filter it, refresh it, and select
an artifact without exposing rendered payloads or storage/runtime internals.

## Scope

- Mount an artifact library toolbar, feedback area, metadata summary, and list
  surface in `apps/nex-ae-web/index.html`.
- Connect `apps/nex-ae-web/src/main.js` to `artifactClient.listArtifacts()`,
  `artifactCollectionRoute()`, and `artifactLibraryPanel.js`.
- Track the artifact library as an operation in runtime diagnostics.
- Let the local mock artifact record carry owner/workspace refs so the same
  owner-scoped collection filtering used by fetch mode also works in mock mode.
- Keep artifact selection metadata-only: selecting a library item reads artifact
  detail metadata through the artifact client and refreshes the existing preview
  and version panels.

## Boundary

- No new PostgreSQL migration is required in this Slice.
- No browser-rendered artifact content, download payload, storage location,
  database URL, provider endpoint, API key, or service token is added to the AE
  Web shell.
- Protected PostgreSQL/Playwright library smoke remains deferred to the next
  evidence Slice.

## Evidence

- `npm --prefix apps/nex-ae-web test`
- `./scripts/quality/run_quality_gate.sh`
