# Slice 0250: OA-Backed AE Auth PostgreSQL Smoke Evidence

## Scope

Add a protected PostgreSQL smoke runner proving that the AE browser-session
facade can use OA-backed opaque browser cookies against real test databases.

## Implemented

- Added `scripts/smoke/run_ae_oa_auth_postgres_smoke.py`.
- The runner is disabled by default and only executes when
  `NEX_AE_OA_AUTH_POSTGRES_SMOKE=1`.
- The runner requires the `test` profile and rejects database URLs that do not
  target `*_test` databases.
- The smoke executes both service migrations before writes:
  - `nex-ae-api` using `NEX_AE_TEST_DATABASE_URL`
  - `nex-oa` using `NEX_OA_TEST_DATABASE_URL`
- The smoke writes/selects/deletes an AE operational-event marker to prove AE
  test DB connectivity.
- The smoke seeds an OA tenant membership, then drives the AE auth facade:
  `login -> current-session -> protected-route auth -> logout -> rejected current-session`.
- The AE facade delegates OA mode calls through the Slice 0248 client seam while
  the OA app uses PostgreSQL-backed subject, membership, and session registries.
- Evidence includes redacted database URLs, migration counts, DB readback
  observations, auth observations, adapter operations, checks, and cleanup
  counts without raw passwords, DB URLs, access tokens, service tokens, or cookie
  material.
- Added the runner to the default quality gate as a protected skip.

## Behavior

- Default quality gate behavior is safe:
  `ae_oa_auth_postgres_smoke=skipped reason=NEX_AE_OA_AUTH_POSTGRES_SMOKE`.
- When enabled against real test DBs, the runner must prove:
  - AE and OA persistence runtime modes are `postgres`.
  - AE marker insert/select succeeds.
  - OA membership and session rows are persisted.
  - AE browser cookie is set on login and removed on logout.
  - AE protected route auth derives tenant/user owner scope from OA
    introspection.
  - OA session is revoked and post-logout introspection is inactive.
  - Cleanup removes all smoke rows.

## Operator Command

```bash
NEX_AE_OA_AUTH_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:<password>@127.0.0.1:5432/nex_ae_test' \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:<password>@127.0.0.1:5432/nex_oa_test' \
./.venv/bin/python scripts/smoke/run_ae_oa_auth_postgres_smoke.py --summary
```

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_ae_oa_auth_postgres_smoke.py -q`
  - Result: `10 passed, 1 warning`
- Actual PostgreSQL test DB smoke:
  `NEX_AE_OA_AUTH_POSTGRES_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_ae_oa_auth_postgres_smoke.py --summary`
  - Result: `ae_oa_auth_postgres_smoke=pass profile=test ae_db=NEX_AE_TEST_DATABASE_URL oa_db=NEX_OA_TEST_DATABASE_URL oa_session_status=REVOKED`
- Full regression and quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1771 passed, 1 warning`
  - Statement coverage: `98.13%`
  - Branch coverage: `94.28%`
