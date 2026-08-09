# Slice 0179: AG Retrieval Package PostgreSQL Smoke Evidence

## Scope

Slice 0179 adds protected PostgreSQL smoke evidence that AG can read persisted
CX retrieval package rows through the operator/debug APIs.

Implemented:

- `scripts/smoke/run_ag_retrieval_package_postgres_smoke.py`
- quality gate skip integration
- PostgreSQL test smoke suite stage `ag_retrieval_package_postgres`
- SQLite-backed regression coverage for AG list/detail/trace execution paths
- redaction checks for raw query text, raw evidence text, principal ids, and
  database passwords

## Decision

The smoke is skipped by default and writes only when:

- `NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE=1`
- `NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE_PROFILE=test`

When enabled, it applies CX migrations to the test profile, seeds the minimal
source/content/extraction/chunk/retrieval package rows required by the CX
foreign keys, reads them through AG's retrieval package list/detail APIs, verifies
the package appears in the cross-service trace timeline, and removes all smoke
rows afterward.

The smoke validates AG's read-side contract only. CX repository write-through
remains covered by Slice 0175.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py -q
```

Observed result:

```text
115 passed, 1 warning
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1385 passed, 1 warning
statement_coverage=98.06% threshold=95.00%
branch_coverage=93.54% threshold=85.00%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
ag_retrieval_package_postgres_smoke=skipped reason=NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE
postgres_test_smoke_suite=skipped reason=NEX_POSTGRES_TEST_SMOKE_SUITE
```

Default guarded smoke:

```bash
./.venv/bin/python scripts/smoke/run_ag_retrieval_package_postgres_smoke.py --summary
```

Observed result:

```text
ag_retrieval_package_postgres_smoke=skipped reason=NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE
```

PostgreSQL test-profile smoke:

```bash
NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE=1 \
NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_ag_retrieval_package_postgres_smoke.py --summary
```

Expected pass line after local test DB connectivity is available:

```text
ag_retrieval_package_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL list=1 detail_evidence=1 timeline=1
```
