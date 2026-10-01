# Slice 1189: MO operations PostgreSQL smoke evidence

## Goal

Prove that the integrated operations snapshot reads restart-safe catalog and
telemetry state from the actual `nex_mo_test` database before adding DGX calls.

## Result

- Added a fail-closed protected smoke guard for the exact
  `nex_mo_user@nex_mo_test` identity and `test` profile.
- Applies all current MO migrations, confirms the catalog, alias, and telemetry
  tables, and reads the actual database identity.
- Writes one success event for each capability under unique telemetry keys,
  recreates the SQLAlchemy engine/repositories, and verifies all three durable
  rows and counters are recovered.
- Calls the authenticated operations API with bounded force refresh, validates
  the canonical schema, and requires four ready sources and three ready
  capabilities.
- Deletes only the three unique smoke telemetry rows and verifies zero residue.
  DGX providers remain outside this Slice.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_operations_postgres_smoke.py
NEX_MO_OPERATIONS_POSTGRES_SMOKE=1 \
NEX_MO_OPERATIONS_POSTGRES_SMOKE_PROFILE=test \
NEX_MO_TEST_DATABASE_URL='<protected nex_mo_test URL>' \
./.venv/bin/python scripts/smoke/run_mo_operations_postgres_smoke.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```

## Executed evidence

- The protected runner connected as `nex_mo_user@nex_mo_test`, confirmed all
  `9/9` migrations were current (`0` newly applied), persisted and restarted
  `3/3` telemetry rows, and passed all `16/16` checks.
- The authenticated snapshot reported `4/4` ready sources and `3/3` ready
  capabilities; targeted telemetry cleanup left zero residue.
- The protected pytest case independently passed against the actual test
  database.
- The Slice Gate passed `922` tests with `4` protected smoke skips and `1`
  warning in 65 seconds; statement coverage was `99.86%` and branch coverage
  was `99.50%`.
