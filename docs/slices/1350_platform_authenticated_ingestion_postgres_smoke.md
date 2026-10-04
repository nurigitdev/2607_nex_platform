# Slice 1350: Authenticated Ingestion PostgreSQL Smoke

## Goal

Prove the actual protected `test` journey from OA credential login through AE
upload, CX durable processing, MO mock embedding, vector freshness, API restart,
and owner-scoped progress readback.

## Implementation

- Added an opt-in subprocess smoke for OA, MO, CX, AE, and the executable CX
  ingestion worker.
- Runs all five service test-database migrations before startup and uses the
  real AE-to-CX and CX-to-MO signed service-token path.
- Polls the authenticated AE progress endpoint until `INDEX_READY`, then
  restarts AE and CX and verifies the same browser session can read the durable
  result.
- Observes AE handoff metadata, CX extraction/chunks, job/run completion,
  summary/summary-embedding metadata, vector payload, and vector-index
  readiness directly in PostgreSQL.
- Verifies unauthenticated denial and signed-service cross-owner hiding.
- Deletes the created AE, CX, and OA rows and temporary storage, then requires
  zero residue.
- Initializes cleanup access as soon as upload identifiers exist, so a worker
  failure before `INDEX_READY` also removes its partial AE/CX lineage.
- Fixed AE progress registration so protected browser cookies use OA session
  introspection instead of the local mock-token validator.
- Added a CX PostgreSQL prompt registry adapter so summary render events and
  summary metadata use the database seed's canonical prompt UUID lineage.

## Guardrails

- The smoke is disabled unless
  `NEX_PLATFORM_AUTHENTICATED_INGESTION_POSTGRES_SMOKE=1`.
- MO uses the protected `test` profile's mock embedding provider. DGX and live
  provider availability are not required for S135.
- Evidence excludes source text, credentials, tokens, database URLs, storage
  paths, and embedding vectors.
- No database table or migration was added.

## Evidence

- Actual protected PostgreSQL smoke: `PASS`; five test databases migrated,
  four service APIs plus the CX worker executed over HTTP/process boundaries,
  two AE/CX generations restored `INDEX_READY`, both denial checks passed, and
  AE/CX/OA/storage residue counts were all zero.
- Final focused progress, prompt persistence, and evidence regression:
  `36 passed`; the expanded prompt persistence branch suite reached `6 passed`.
- CX Slice Gate: `2,341 passed`; statement coverage `99.09%`, branch coverage
  `98.20%`.
- Changed CX prompt persistence, CX prompt composition, and AE progress scopes:
  statement `100%`, branch `100%`.
- Contract validation: `159` schemas, `216` positive examples, `186` negative
  examples, and `7` OpenAPI documents.

## Result

Slice 1350 closes the actual PostgreSQL and restart evidence gap. Slice 1351
can now close the S135 contracts, privacy rules, runbook, and Full Gate before
the live-provider S136 handoff.
