# Slice 0967: CX Restart-Safe Generation Read Model

## Goal

Make owner-scoped generation metadata and generated content readable after a
CX process restart without exposing private payloads through the default
generation projection.

## Implementation

- Added a read model backed by the durable generation repository and the
  owner-private text store.
- Made `GET /api/v1/generations/{cx_generation_id}` prefer the durable
  owner-scoped projection when PostgreSQL persistence is active.
- Removed storage backend and URI details from that projection. It exposes
  only content availability, SHA-256, and byte size.
- Added explicit `GET /api/v1/generations/{cx_generation_id}/content` access.
  It reloads the owner-private payload and verifies its hash and byte size.
- Cross-owner access is indistinguishable from a missing generation.
- Failed executions, missing references, missing payloads, and repository or
  integrity failures fail closed with stable problem responses.
- Preserved the legacy in-memory structured-draft and progress-event routes;
  historical event persistence is intentionally not inferred from terminal
  execution metadata.

## Verification

SQLite regression covers restart simulation, owner isolation, private
projection redaction, content integrity failures, missing payloads, failed
executions, route authentication, and main runtime composition. Actual
PostgreSQL and DGX generation remain reserved for Slice 0969.

Observed results:

- focused read-model regression: `10 passed`, statement `100%`, branch `100%`
- related generation and contract regression: `114 passed`
- full regression: `7,471 passed`
- full statement coverage: `98.89%`
- full branch coverage: `96.61%`
- contract validation: `87` schemas, `138` examples, `103` negative
  examples, and `7` OpenAPI documents
- quality gate exit status: `0`
