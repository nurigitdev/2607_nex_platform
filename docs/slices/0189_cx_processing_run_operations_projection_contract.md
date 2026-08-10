# Slice 0189: CX Processing Run Operations Projection Contract

## Scope

Slice 0189 freezes the AG operations projection contract for CX processing run
observability before wiring AG to the persisted CX read path.

Implemented:

- `ag_cx_processing_run_operations_projection.v1`
- `ag_cx_processing_run_detail_projection.v1`
- `cx_processing_run_operation` and `cx_processing_step_operation` schema defs
- list and detail positive contract examples
- raw error detail negative contract example
- CX processing persistence decision update to
  `operations_projection_contract_ready`

## Decision

AG may expose CX processing run metadata for operator debugging, but the
projection remains metadata-only. It includes status, trace/request/job
correlation, step counts, safe output references, timestamps, and error hashes.

The contract explicitly excludes raw source text, extracted markdown, chunk
text, summary text, embeddings/vectors, raw prompts, raw step output, private
payloads, and raw error details. Failed step diagnostics use
`error_code`, `error_detail_sha256`, and `error_retryable`.

The list projection can return processing runs without steps for dashboard and
table views. The detail projection can include step metadata for drilldown.

## Next Slice

Recommended next slice:

- `0190_ag_cx_processing_operations_projection_postgres_smoke`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py -q
```

Expected result:

```text
pass
```

Observed targeted result:

```text
25 passed
```

Full contract validation:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Expected result:

```text
contract_validation=pass
```

Observed contract result:

```text
contract_validation=pass schemas=42 examples=71 negative_examples=49 openapi=7
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1433 passed
statement_coverage=98.06%
branch_coverage=93.65%
contract_validation=pass
```
