# Slice 0175: CX Retrieval PostgreSQL Smoke Evidence

## Scope

Slice 0175 adds protected PostgreSQL smoke evidence for CX retrieval package
persistence.

Implemented:

- `scripts/smoke/run_cx_retrieval_postgres_smoke.py`
- quality gate skip integration
- PostgreSQL test smoke suite stage `cx_retrieval`
- SQLite-backed regression coverage for the smoke execution path
- audit checkpoint update from Slice 0171 to Slice 0175

## Decision

The smoke is skipped by default and writes only when:

- `NEX_CX_RETRIEVAL_POSTGRES_SMOKE=1`
- `NEX_CX_RETRIEVAL_POSTGRES_SMOKE_PROFILE=test`

When enabled, it applies the CX migrations to the test profile, writes an upload,
extraction artifact, chunk set, and retrieval package through the real
SQLAlchemy repository, verifies hash/preview-only persistence, and removes smoke
rows afterward.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py tests/test_nex_cx_persistence_audit.py tests/test_nex_cx_repository.py tests/test_nex_cx_retrieval_persistence.py
```

Observed result:

```text
215 passed, 1 warning
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1365 passed, 1 warning
statement_coverage=98.22% threshold=95.00%
branch_coverage=94.03% threshold=85.00%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
cx_retrieval_postgres_smoke=skipped reason=NEX_CX_RETRIEVAL_POSTGRES_SMOKE
postgres_test_smoke_suite=skipped reason=NEX_POSTGRES_TEST_SMOKE_SUITE
```

PostgreSQL test-profile smoke:

```bash
NEX_CX_RETRIEVAL_POSTGRES_SMOKE=1 \
NEX_CX_RETRIEVAL_POSTGRES_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_cx_retrieval_postgres_smoke.py --summary
```

Observed result:

```text
cx_retrieval_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL
```

PostgreSQL test-profile suite, scoped to `nex-cx`:

```bash
NEX_POSTGRES_TEST_SMOKE_SUITE=1 \
NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES=nex-cx \
NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_postgres_test_smoke_suite.py --summary
```

Observed result:

```text
postgres_test_smoke_suite=pass services=1 profile=test primary=nex-cx stages=14
```
