# Slice 1160: MO provider telemetry PostgreSQL smoke evidence

## Goal

Prove that durable provider telemetry survives an actual database-engine
restart, preserves atomic concurrent counters, remains privacy-safe through the
authenticated API, and leaves no test residue in `nex_mo_test`.

## Result

- Added a protected smoke that accepts only `nex_mo_user@nex_mo_test` and is
  skipped unless its explicit activation flag is enabled.
- Applies all MO migrations, verifies the compact telemetry table, and records
  one retry plus 24 parallel success/failure terminal events.
- Disposes the first SQLAlchemy engine, creates a fresh engine and repository,
  then proves exact recovered counters and monotonic latest diagnostics.
- Queries the authenticated telemetry API and checks the established 26-field
  projection without exposing endpoint, API key, token, database password, or
  storage key values.
- Deletes only the smoke's unique telemetry row and verifies zero residue.
- This persistence smoke makes no remote DGX provider request.

## Verification

```bash
NEX_MO_PROVIDER_TELEMETRY_POSTGRES_SMOKE=1 \
NEX_MO_PROVIDER_TELEMETRY_POSTGRES_SMOKE_PROFILE=test \
NEX_MO_TEST_DATABASE_URL='<protected nex_mo_test URL>' \
./.venv/bin/python \
  scripts/smoke/run_mo_provider_telemetry_postgres_smoke.py --summary

scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_telemetry_postgres_smoke.py \
  --smoke scripts/smoke/run_mo_provider_telemetry_postgres_smoke.py
```

## Quality Evidence

- Protected PostgreSQL pytest ran instead of skipping: `1 passed`.
- Actual `nex_mo_user@nex_mo_test` smoke: `11/11` checks passed; the first run
  applied the new telemetry migration (`1 applied + 7 current / 8 planned`),
  and the repeated run confirmed all eight migrations current.
- The protected smoke applied `25` mutations through eight workers, recovered
  exact `24` request and `25` attempt counts after a fresh engine, matched the
  authenticated API projection, and left cleanup residue `0`.
- The first actual run exposed PostgreSQL session-timezone rendering of a UTC
  instant. Durable mapping now canonicalizes database datetime and string
  values to UTC `Z`, with focused regression coverage.
- Focused persistence/repository/smoke regression: `44 passed`, `1` protected
  skip in the default environment.
- Slice Gate: `606 passed`, `2` protected PostgreSQL skips; statement coverage
  `99.76%`, branch coverage `99.08%`, and changed persistence scope
  `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
