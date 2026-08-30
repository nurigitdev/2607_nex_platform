# Slice 0433: AE Web Artifact Download Action Wiring

## Scope

Wire AE Web artifact download clicks to the browser file-save adapter added in
Slice 0432.

## Changes

- `apps/nex-ae-web/src/main.js` now imports `saveArtifactDownload` and
  `buildArtifactDownloadSaveSummary`.
- Successful download actions still build the metadata-only preview/download
  panel state, then call the browser save adapter.
- The artifact preview/download operation records the save result status
  (`SAVED` or `PREPARED`) as safe operation metadata through `resultStatus`.
- Added `apps/nex-ae-web/test/artifactDownloadActionWiring.test.mjs` to keep
  the download fetch, panel state, and browser-save ordering fixed.

## Decisions

- The browser panel remains metadata-only even after a file save is attempted.
- Save errors flow through the existing artifact preview/download operation
  failure path.
- This slice does not add PostgreSQL smoke because no backend route or
  persisted data path changed.

## Evidence

Targeted browser-side regression:

```bash
node --test apps/nex-ae-web/test/artifactDownloadActionWiring.test.mjs apps/nex-ae-web/test/artifactDownloadSaveAdapter.test.mjs apps/nex-ae-web/test/artifactPreviewPanel.test.mjs
```

Full AE Web regression:

```bash
npm --prefix apps/nex-ae-web test
```
