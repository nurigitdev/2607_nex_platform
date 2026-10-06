# Slice 1380: Platform AG Trace PostgreSQL Smoke

## Goal

Prove the S138 service-API-only trace against the actual OA, AE, CX, MO, and AG
test PostgreSQL databases without calling remote model providers.

## Implementation

- Added a protected runner that applies all five migration chains, verifies the
  expected test database and role identities, and seeds one correlated trace in
  service-owned tables only.
- Built OA, AE, CX, and MO internal trace APIs over their actual PostgreSQL
  repositories, then called them through the typed AG HTTP source clients. AG
  did not read another service database.
- Added metadata-only AE preview/download access audit events and projected
  them as the canonical `ACCESS` stage. An unavailable durable audit store now
  fails the browser-facing access request closed.
- Normalized PostgreSQL UUID identifiers in the CX trace projection. Psycopg
  returns UUID columns as `UUID` objects, while the earlier SQLite regression
  path returned strings.
- Reopened the AG operational-event store after engine disposal and verified
  that the trace-read audit survived restart.
- Added bounded step failure codes and enabled cleanup before the first seed so
  a partially failed journey cannot leave new fixtures behind.

The runner is protected by `NEX_S138_AG_TRACE_POSTGRES_SMOKE=1`, accepts only
the `test` profile and the five expected test database/role pairs, and is safe
to invoke from the Full Gate because it skips unless explicitly enabled.

## Actual Evidence

The protected run used `nex_oa_test`, `nex_ae_test`, `nex_cx_test`,
`nex_mo_test`, and `nex_ag_test` through their service-local roles.

```text
platform_ag_trace_postgres_smoke=pass checks=9/9 services=5 families=8 residue=0 next=1381
```

Observed facts:

- `94` migrations were current across the five services.
- All five database and role identities matched the protected test targets.
- OA, AE, CX, and MO source APIs plus the AG projection were `READY`.
- All eight stage families were reconstructed: `AUTH`, `UPLOAD`, `INGESTION`,
  `RETRIEVAL`, `GENERATION`, `ARTIFACT`, `ACCESS`, and `OPERATIONS`.
- The AG audit survived a store restart, private payload detection remained
  false, direct cross-database reads remained zero, and cleanup residue was
  zero in every database.
- Three OA fixtures left by pre-hardening failed attempts were identified by
  the dedicated `request-oa-s138-*` prefix and removed from `nex_oa_test`.

## Verification

```bash
NEX_S138_AG_TRACE_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='<oa-test-url>' \
NEX_AE_TEST_DATABASE_URL='<ae-test-url>' \
NEX_CX_TEST_DATABASE_URL='<cx-test-url>' \
NEX_MO_TEST_DATABASE_URL='<mo-test-url>' \
NEX_AG_TEST_DATABASE_URL='<ag-test-url>' \
./.venv/bin/python scripts/smoke/run_platform_ag_trace_postgres_smoke.py --summary
```

Remote embedding, reranking, and generation providers are not required because
this Slice reconstructs already persisted operations metadata rather than
executing model inference.

Slice Gate evidence:

- regression: `2928 passed`, `5` policy-skipped protected tests
- statement coverage: `98.34%`
- branch coverage: `96.23%`
- AE access observability: statement `100.00%`, branch `100.00%`
- AE trace projection: statement `99.45%`, branch `98.21%`
- CX trace projection: statement `99.35%`, branch `98.00%`
- PostgreSQL smoke coordinator: statement `100.00%`, branch `100.00%`
- contract validation: `166` schemas, `228` examples, `196` negative
  examples, and `7` OpenAPI documents
