# Slice 1130: MO provider readiness live PostgreSQL and DGX smoke

## Goal

Prove the S113 readiness surface against the actual `nex_mo_test` database and
all three current DGX providers without exposing provider endpoints,
credentials, database passwords, or request/response payloads.

## Implementation

- Added an explicit protected runner that accepts only the `test` profile and
  requires the actual MO test database plus live embedding, reranking, and
  generation configuration.
- Exercised `GET /ready`, which performs the real PostgreSQL
  `current_database()/current_user` query and active provider preflights.
- Exercised the authenticated `GET /api/v1/provider-route-health` projection
  and its unauthenticated 401 guard.
- Verified the API reused the fresh readiness snapshot rather than issuing a
  second provider probe set.
- Validated both provider projections against the canonical JSON Schema and
  restricted evidence to database identity, current model revisions, bounded
  latency, aggregate statuses, and redaction metadata.
- No migration is required because this is a read-only readiness boundary and
  S113 intentionally creates no durable table.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_readiness_live_postgres_smoke.py

NEX_MO_PROVIDER_READINESS_LIVE_POSTGRES_SMOKE=1 \
  ./.venv/bin/python \
  scripts/smoke/run_mo_provider_readiness_live_postgres_smoke.py --summary
```

The protected command must receive database, endpoint, and credential values
through the process environment. They are intentionally absent from this
document and from committed evidence.

## Observed Evidence

- Actual PostgreSQL identity: `nex_mo_user@nex_mo_test`.
- Actual DGX active preflight: embedding, reranking, and generation `3/3`
  READY using `Qwen3-Embedding-4B`, `Qwen3-Reranker-4B`, and `Qwen3.5-4B`.
- Protected checks: `8/8`; unauthorized route: HTTP 401; both authorized
  readiness surfaces: HTTP 200; fresh snapshot reuse confirmed.
- Slice Gate: `405 passed`; statement coverage `99.69%`; branch coverage
  `98.82%`; new smoke scope statement/branch coverage `100%`.
- Contract validation: `110` schemas, `168` positive examples, `133` negative
  examples, and `7` OpenAPI documents.
