# Slice 0180: Retrieval Observability Contract Examples Closure

## Scope

Slice 0180 closes the AG retrieval observability contract/example gap created by
Slices 0176-0179.

Implemented:

- positive contract examples for retrieval package list, detail, and trace
  timeline correlation
- negative contract examples for missing retrieval source status and raw
  evidence preview leakage
- stricter `operations_projection.v1` retrieval package/evidence item defs
- trace timeline retrieval package payload alignment with the list/detail
  projection shape
- regression coverage for the new timeline payload fields and numeric helper
  edge cases

## Decision

AG retrieval observability remains metadata-only. The contract now permits
bounded query previews for operator correlation, but evidence text preview,
raw evidence text, and raw text fields are invalid inside AG evidence items.
Permission projections also reject `principal_id` so detail views can expose
permission outcome metadata without leaking user identifiers.

The trace timeline's `retrieval_package` payload now carries the same core
operation metadata as retrieval package list/detail projections. This keeps
operator drilldown and trace correlation examples stable before the next CX/AE
workflow slices.

## Evidence

Contract validation:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Observed result:

```text
contract_validation=pass schemas=42 examples=69 negative_examples=48 openapi=7
```

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_ag_retrieval_operations.py tests/test_contract_validation.py -q
```

Observed result:

```text
164 passed, 1 warning
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1386 passed, 1 warning
statement_coverage=98.07% threshold=95.00%
branch_coverage=93.55% threshold=85.00%
contract_validation=pass schemas=42 examples=69 negative_examples=48 openapi=7
ag_retrieval_package_postgres_smoke=skipped reason=NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE
postgres_test_smoke_suite=skipped reason=NEX_POSTGRES_TEST_SMOKE_SUITE
```
