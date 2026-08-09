# Slice 0178: AG Trace Timeline Retrieval Package Correlation

## Scope

Slice 0178 extends the AG cross-service trace timeline so retrieval package
records can appear beside jobs, operational events, and structured service logs.

Implemented:

- optional `retrieval_package_stores` source wiring for
  `GET /admin/v1/operations/traces/{trace_id}`
- `retrieval_package` timeline items keyed by service id and package id
- `retrieval_package_source_statuses` source diagnostics
- contract schema support for retrieval package list/detail projections and
  retrieval package timeline items
- AG app wiring from the Slice 0176 retrieval package stores into the unified
  trace timeline route
- regression coverage for timeline sorting, source status, route wiring, and
  unavailable retrieval package sources

## Decision

Retrieval package trace correlation is optional and backward compatible. Older
trace timeline examples remain valid without `retrieval_package_source_statuses`.
When the source is configured, AG adds CX retrieval package metadata for the
trace without exposing evidence text, vectors, or storage paths.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_ag_retrieval_operations.py
```

Observed result:

```text
148 passed, 1 warning
```

Contract validation:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Observed result:

```text
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1378 passed, 1 warning
statement_coverage=98.06% threshold=95.00%
branch_coverage=93.56% threshold=85.00%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
```
