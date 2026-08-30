# Slice 0437: AE Web Artifact Download Format Selector

## Scope

Add a browser-safe selector for artifact download formats so multi-format
artifacts can expose one visible delivery surface without duplicating download
state logic.

## Changes

- Added `apps/nex-ae-web/src/artifactDownloadFormatSelector.js`.
- Added `apps/nex-ae-web/test/artifactDownloadFormatSelector.test.mjs`.
- `apps/nex-ae-web/src/main.js` now renders the selector in the artifact
  summary and routes selector clicks through the existing artifact download
  action path.
- Added compact selector styles in `apps/nex-ae-web/src/styles.css`.

## Decisions

- The selector validates every enabled route with the existing artifact file
  download route parser.
- Disabled options are visible when a format is known but no download route is
  available yet.
- Selector summaries omit raw routes and payloads; rendered browser controls may
  carry same-origin `/api/v1/artifact-files/{id}/download` routes as action
  attributes.
- This slice is browser-only and does not require PostgreSQL smoke.

## Evidence

Targeted browser-side regression:

```bash
node --test apps/nex-ae-web/test/artifactDownloadFormatSelector.test.mjs apps/nex-ae-web/test/artifactDeliveryActionState.test.mjs apps/nex-ae-web/test/artifactDownloadActionWiring.test.mjs
```
