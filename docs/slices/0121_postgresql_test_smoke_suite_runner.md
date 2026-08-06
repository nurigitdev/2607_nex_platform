# Slice 0121: PostgreSQL Test Smoke Suite Runner

## Scope

Slice 0121 adds one guarded suite runner for PostgreSQL test-profile smoke
evidence. The runner keeps the default regression path fast and SQLite-centered,
while making it possible to execute the staged PostgreSQL confidence checks with
one command when local test databases are available.

Implemented:

- `scripts/smoke/run_postgres_test_smoke_suite.py`
- quality gate skip-summary hook
- `NEX_POSTGRES_TEST_SMOKE_SUITE`
- `NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE`
- `NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES`
- `NEX_POSTGRES_TEST_SMOKE_SUITE_PRIMARY_SERVICE`
- regression coverage for skipped, validation, pass, staged failure, and summary
  behavior

## Suite Stages

The suite runs stages in this order:

1. database readiness for selected service test DBs
2. service migrations for selected service test DBs
3. primary-service JobQueue PostgreSQL smoke
4. primary-service OperationalEventStore PostgreSQL smoke
5. cross-service DB operations smoke pack
6. CX processing PostgreSQL JobQueue smoke
7. CX processing PostgreSQL operational event smoke
8. AG cross-service observability smoke

`nex-cx` is the only supported primary service for this suite because the
downstream CX processing and AG observability smokes are CX-centered.

## Safety Boundary

Default behavior is skipped:

```text
postgres_test_smoke_suite=skipped reason=NEX_POSTGRES_TEST_SMOKE_SUITE
```

Live execution must explicitly enable the suite and use the `test` profile:

```text
NEX_POSTGRES_TEST_SMOKE_SUITE=1
NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE=test
NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES=nex-ae-api,nex-ag,nex-cx,nex-mo,nex-oa
NEX_POSTGRES_TEST_SMOKE_SUITE_PRIMARY_SERVICE=nex-cx
```

The suite refuses non-test profiles and records redacted database URLs in
evidence. Child smoke runners keep their own cleanup behavior for temporary
rows.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py
```

Default skipped smoke:

```bash
./.venv/bin/python scripts/smoke/run_postgres_test_smoke_suite.py --summary
```

Optional PostgreSQL test suite:

```bash
NEX_POSTGRES_TEST_SMOKE_SUITE=1 \
NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE=test \
NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES=nex-ae-api,nex-ag,nex-cx,nex-mo,nex-oa \
NEX_POSTGRES_TEST_SMOKE_SUITE_PRIMARY_SERVICE=nex-cx \
./.venv/bin/python scripts/smoke/run_postgres_test_smoke_suite.py --summary
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
