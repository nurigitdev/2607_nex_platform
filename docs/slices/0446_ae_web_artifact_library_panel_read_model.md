# Slice 0446: AE Web Artifact Library Panel Read Model

## Scope

Add the AE Web read-model and renderer foundation for an owner-scoped artifact
library panel.

## Changes

- Added `apps/nex-ae-web/src/artifactLibraryPanel.js`.
- Added panel state builders for ready, running, empty, filtered, and
  unavailable artifact library states.
- Added safe item normalization from Slice 0445 collection surfaces.
- Added a compact renderer summary and HTML fragments for the future workspace
  UI wiring.
- Added Node regression coverage for filtering, escaping, invalid inputs, and
  sensitive field/value guards.

## Decisions

- Slice 0446 remains UI-framework neutral. It produces panel state and escaped
  HTML fragments, but does not yet wire the panel into `main.js`.
- The panel supports `all`, `ready`, `failed`, `downloadable`, and `previewable`
  filter modes so Slice 0447 can add a thin browser interaction layer.
- The read-model carries metadata-only fields: artifact IDs, display title,
  status, formats, counts, routes, owner scope, source IDs, and citation
  counters. It excludes rendered payloads, download bytes, source text, storage
  refs, local paths, database URLs, provider endpoints, and credentials.

## Evidence

AE Web regression:

```bash
npm --prefix apps/nex-ae-web test
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
