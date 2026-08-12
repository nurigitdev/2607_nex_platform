# Slice 0244: OA Session PostgreSQL Smoke Evidence

## Scope

Prove that OA membership-backed session issuance can run against the real
`nex_oa_test` PostgreSQL database, with migrations applied and safe cleanup.

## Implemented

- Added protected smoke runner:
  `scripts/smoke/run_oa_session_postgres_smoke.py`.
- The runner requires `NEX_OA_SESSION_POSTGRES_SMOKE=1` and forces the `test`
  profile for write execution.
- The runner applies `nex-oa` migrations, builds the OA app in PostgreSQL
  runtime mode, creates a membership through the HTTP route, issues a session
  through the HTTP route, reads it back, checks DB row counts, and deletes the
  smoke rows.
- Added the smoke summary to the quality gate, where it skips unless explicitly
  enabled.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_oa_session_postgres_smoke.py tests/test_nex_oa_sessions.py -q`
  - Result: `15 passed, 1 warning`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1741 passed, 1 warning`
  - Coverage: statement `98.06%`, branch `94.13%`
  - Contract validation: `pass` with 49 schemas, 78 examples, 54 negative
    examples, and 7 OpenAPI specs.
  - Quality-gate smoke summary includes:
    `oa_session_postgres_smoke=skipped reason=NEX_OA_SESSION_POSTGRES_SMOKE`
- Protected PostgreSQL smoke:
  `NEX_OA_SESSION_POSTGRES_SMOKE=1 NEX_OA_TEST_DATABASE_URL=... ./.venv/bin/python scripts/smoke/run_oa_session_postgres_smoke.py`
  - Result: `PASS`
  - Database env: `NEX_OA_TEST_DATABASE_URL`
  - Redacted URL: `postgresql://nex_oa_user:***@127.0.0.1:5432/nex_oa_test`
  - Migration: planned `10`, applied
    `0242_oa_tenant_membership_foundation` and
    `0243_oa_user_session_foundation`, skipped `8`
  - DB observations: membership count `1`, session count `1`, session status
    `ACTIVE`, scopes `["workspace:use"]`, roles
    `["employee", "smoke-tester"]`
  - Checks: runtime mode, membership route, issue route, readback route,
    session id roundtrip, scope subset, DB persistence, subject match, and raw
    payload redaction all `true`
  - Cleanup: deleted sessions `1`, memberships `1`, subjects `1`, tenants `1`
