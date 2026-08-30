# Slice 0436: AE Web Artifact Delivery Action State

## Scope

Refactor AE Web preview/download action state so success, failure, retry, and
browser save outcomes are decided in one browser-safe module before adding more
delivery behavior.

## Changes

- Added `apps/nex-ae-web/src/artifactDeliveryActionState.js`.
- Added `apps/nex-ae-web/test/artifactDeliveryActionState.test.mjs`.
- `apps/nex-ae-web/src/main.js` now delegates preview/download running,
  success, download-save, and failure transitions to the delivery action state
  module.
- Failure summaries keep retry state and error status, but do not carry raw
  error messages or downloaded payloads.

## Decisions

- `artifactClient.previewArtifactFile` and `artifactClient.downloadArtifactFile`
  remain the only fetch points for artifact file actions.
- `artifactDeliveryActionState` owns the browser-side state transition between
  file action, preview/download panel, operation feedback, and download save
  result.
- Raw text bodies, base64 payloads, service tokens, database URLs, provider
  endpoints, and storage refs remain forbidden in delivery state.
- This slice does not need PostgreSQL smoke because it is a browser-side
  refactoring with deterministic unit coverage.

## Evidence

Targeted browser-side regression:

```bash
node --test apps/nex-ae-web/test/artifactDeliveryActionState.test.mjs apps/nex-ae-web/test/artifactDownloadActionWiring.test.mjs apps/nex-ae-web/test/artifactDownloadSaveAdapter.test.mjs apps/nex-ae-web/test/artifactExportResultReadModel.test.mjs
```
