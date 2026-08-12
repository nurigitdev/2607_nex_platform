# Slice 0239: Authenticated Fetch-Mode PostgreSQL Smoke Evidence

## Scope

Slice 0239 upgrades the AE Web fetch-mode PostgreSQL smoke so it exercises the
same browser-user route guard introduced in Slice 0238.

Implemented:

- Updated `scripts/smoke/run_ae_web_fetch_mode_postgres_smoke.py` so AE facade
  calls use mock browser user tokens instead of AE-facing service tokens.
- Kept AE-to-CX calls service-token based, preserving the internal service
  boundary.
- Omitted owner fields from the upload request and verified AE derives owner
  scope from the authenticated browser claim.
- Verified retrieval actor scope is claim-derived.
- Added `auth_observations` and browser claim checks to the PASS evidence
  contract and fixtures.
- Extended regression tests for the updated protected evidence shape.

## Boundary

The smoke still requires the protected execution flag and `test` profile before
touching PostgreSQL. PASS evidence records only enum/boolean auth observations;
it does not expose raw browser tokens, service tokens, database URLs, tenant
IDs, user IDs, source text, storage roots, storage keys, or provider endpoints.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_ae_web_fetch_mode_postgres_smoke.py tests/test_contract_validation.py -q
```

Observed targeted result:

```text
37 passed, 1 warning in 2.20s
```

Protected PostgreSQL smoke against `nex_ae_test` and `nex_cx_test`:

```bash
NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE=1 \
NEX_AE_WEB_FETCH_MODE_PROFILE=test \
NEX_AE_WEB_FETCH_MODE_SMOKE_WEB_URL=http://127.0.0.1:5227 \
NEX_AE_WEB_FETCH_MODE_SMOKE_AE_API_BASE_URL=http://127.0.0.1:8103 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test' \
NEX_AE_WEB_FETCH_MODE_SMOKE_TENANT_ID=<redacted> \
NEX_AE_WEB_FETCH_MODE_SMOKE_OWNER_USER_ID=<redacted> \
./.venv/bin/python scripts/smoke/run_ae_web_fetch_mode_postgres_smoke.py --summary
```

Observed protected smoke:

```text
ae_web_fetch_mode_postgres_smoke=pass profile=test ae_db=NEX_AE_TEST_DATABASE_URL cx_db=NEX_CX_TEST_DATABASE_URL retrieval_evidence=1
auth_observations.ae_facade_auth_mode=browser_user
auth_observations.owner_scope_authority=claim
checks.browser_claim_owner_scope_enforced=true
checks.retrieval_actor_scope_claim_derived=true
cleanup.ae_marker_rows_after_delete=0
cleanup.cx_retrieval_rows.evidence_rows_after_delete=0
cleanup.cx_retrieval_rows.package_rows_after_delete=0
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed full quality gate:

```text
1707 passed, 1 warning in 61.41s
statement_coverage=98.05% threshold=95.00%
branch_coverage=93.97% threshold=85.00%
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
