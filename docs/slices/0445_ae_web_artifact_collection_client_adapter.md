# Slice 0445: AE Web Artifact Collection Client Adapter

## Scope

Add the AE Web client adapter foundation for browsing owner-scoped artifact
collections.

## Changes

- Added artifact collection schema constants and route/query builders to
  `apps/nex-ae-web/src/artifactClient.js`.
- Added `listArtifacts()` to mock and fetch artifact clients.
- Added browser-safe collection surface, item, and summary builders.
- Extended AE Web artifact client tests for query validation, route generation,
  owner/status/limit filtering, fetch-mode route shape, malformed payloads, and
  redaction.

## Decisions

- The browser client targets `GET /api/v1/artifacts` with explicit
  `tenant_id`, `workspace_id`, `owner_user_id`, optional `status`, and bounded
  `limit`.
- Mock mode mirrors the service-side owner-scoped filter so the upcoming
  library panel can run without a live AE API.
- Collection surfaces stay metadata-only. They include routes, counts, formats,
  owner scope, source summary, and quality summary, but exclude rendered
  payloads, download bytes, storage refs, local paths, database URLs, provider
  endpoints, and credentials.

## Evidence

AE Web regression:

```bash
npm --prefix apps/nex-ae-web test
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
