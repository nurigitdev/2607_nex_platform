# Slice 0455: AE Web Artifact Lifecycle Client Adapter

## Goal

Add AE Web client support for artifact lifecycle actions without introducing
browser-side storage mutation or raw comment evidence.

## Scope

- Added lifecycle constants, route construction, request normalization, and
  result-surface builders to `apps/nex-ae-web/src/artifactClient.js`.
- Added `submitArtifactLifecycleAction` to both mock and fetch artifact clients.
- Kept `ARCHIVE`, `RESTORE`, and `MARK_DELETED` aligned with the AE API
  lifecycle contract from Slice 0452.
- Kept raw lifecycle comments only in outbound POST bodies; browser surfaces and
  summaries expose only comment length and hash-presence metadata.

## Evidence

- `npm --prefix apps/nex-ae-web test`
  - `227 passed`
- Added regression coverage for lifecycle request building, mock state
  transitions, same-origin fetch POST wiring, unsafe metadata rejection, invalid
  restore targets, and sensitive-value guards.

## Notes

- PostgreSQL smoke remains in the AE API lifecycle smoke path from Slice 0454.
- Browser Playwright/PostgreSQL evidence is deferred to the future lifecycle UX
  wiring Slice, where the actual controls and authenticated fetch runtime are
  exercised together.
