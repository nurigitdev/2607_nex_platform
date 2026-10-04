# Slice 1304: Platform runtime profile, mock residue, and direct-call audit

## Outcome

- Confirmed the five documented runtime profiles remain `local_mock`,
  `local_live`, `test`, `staging_live`, and `production`.
- Confirmed repository defaults remain deliberately mock-first: MO providers
  use `mock`, persistence uses `memory`, AG operations projections use
  `memory`, and AE Web uses mock clients with fetch disabled.
- Confirmed OA, AE API, CX, and AG do not reference remote embedding,
  reranking, or generation provider endpoint environment variables. Remote
  provider host ownership remains isolated to MO.
- Confirmed the current multi-service runner starts all five backend service
  shells but does not start AE Web, wait for readiness, or validate a typed
  runtime profile.
- Recorded profile materialization and readiness-gated startup as P0 S132
  work. Mock-first behavior remains the deterministic regression baseline.

## Decision

The existing defaults are retained. S131 will not turn repository regression
into a live-provider or PostgreSQL-only workflow. The current process runner is
a developer convenience, not the accepted release topology. S132 must convert
the documented profile names into one validated manifest that controls service
URLs, persistence, provider mode, startup order, and readiness without exposing
provider endpoints outside MO.

No database or remote provider is required for this repository audit Slice.

## Verification

- Focused tests: `5 passed`.
- Slice Gate (`nex-mo`): `1,063 passed`, `6 skipped` protected smokes.
- Coverage: statement `99.83%`, branch `99.39%`.
- Changed audit runner coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- Audit summary: `5` documented profiles, `5` backend runner services,
  AE Web absent from the runner, no readiness wait, and `0` forbidden direct
  provider endpoint references outside MO.
