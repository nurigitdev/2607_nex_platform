# Slice 0229: AE Web Fetch-Mode PostgreSQL Smoke Evidence Execution

## Scope

Slice 0229 turns the Slice 0228 protected boundary into an executable protected
PostgreSQL smoke path.

Implemented:

- Added `scripts/smoke/run_ae_web_fetch_mode_postgres_smoke.py`.
- The runner is skipped by default and executes only when
  `NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE=1`.
- The enabled path validates the Slice 0228 boundary, allows only the `test`
  profile, rejects non-`*_test` database URLs, and runs AE/CX migrations against
  the supplied test databases.
- The smoke writes and reads an AE API operational-event marker in
  `nex_ae_test`, then exercises AE upload, document detail, and retrieval facade
  routes against a CX store backed by `nex_cx_test`.
- The CX side persists upload metadata, extraction/chunk/lexical/embedding
  metadata, and retrieval package evidence, then reads the persisted retrieval
  package back from PostgreSQL.
- Added regression tests for skip/fail/pass branches, safe redaction, facade
  execution with fake DB adapters, client error handling, DB marker SQL shape,
  retrieval readback helpers, URL guards, and CLI output.
- Wired the protected runner into the default quality gate in skipped mode.

## Boundary

This remains a protected smoke, not a default CI PostgreSQL run. The default
quality gate must finish without local database credentials and report skipped.
When enabled, however, the runner must actually connect to the supplied test
databases and either pass with write/readback evidence or fail.

Required enabled env:

```text
NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE=1
NEX_AE_WEB_FETCH_MODE_SMOKE_PROFILE=test
NEX_AE_WEB_FETCH_MODE_SMOKE_WEB_URL=http://127.0.0.1:5227
NEX_AE_WEB_FETCH_MODE_SMOKE_AE_API_BASE_URL=http://127.0.0.1:8103
NEX_AE_TEST_DATABASE_URL=<AE test database URL>
NEX_CX_TEST_DATABASE_URL=<CX test database URL>
NEX_AE_WEB_FETCH_MODE_SMOKE_TENANT_ID=<smoke tenant>
NEX_AE_WEB_FETCH_MODE_SMOKE_OWNER_USER_ID=<smoke owner>
```

The runner redacts database URLs and never includes raw source text, source
storage paths, service tokens, or provider endpoints in evidence.

## Evidence

Targeted Python regression:

```bash
./.venv/bin/pytest tests/test_ae_web_fetch_mode_postgres_smoke.py -q
```

Protected runner skipped summary:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_fetch_mode_postgres_smoke.py --summary
```

Protected PostgreSQL smoke:

```bash
NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE=1 \
NEX_AE_WEB_FETCH_MODE_SMOKE_PROFILE=test \
NEX_AE_WEB_FETCH_MODE_SMOKE_WEB_URL=http://127.0.0.1:5227 \
NEX_AE_WEB_FETCH_MODE_SMOKE_AE_API_BASE_URL=http://127.0.0.1:8103 \
NEX_AE_TEST_DATABASE_URL='<redacted AE test database URL>' \
NEX_CX_TEST_DATABASE_URL='<redacted CX test database URL>' \
NEX_AE_WEB_FETCH_MODE_SMOKE_TENANT_ID=tenant-slice-0229 \
NEX_AE_WEB_FETCH_MODE_SMOKE_OWNER_USER_ID=owner-slice-0229 \
./.venv/bin/python scripts/smoke/run_ae_web_fetch_mode_postgres_smoke.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
17 passed, 1 warning in 1.34s
```

Observed protected PostgreSQL smoke:

```text
ae_web_fetch_mode_postgres_smoke=pass profile=test ae_db=NEX_AE_TEST_DATABASE_URL cx_db=NEX_CX_TEST_DATABASE_URL retrieval_evidence=1
remaining_fetch_mode_smoke_rows=0
```

Observed full quality gate:

```text
1665 passed, 1 warning in 56.80s
statement_coverage=98.04% threshold=95.00%
branch_coverage=93.88% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
