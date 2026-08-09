# Slice 0177: AG Retrieval Package Detail Debug Projection

## Scope

Slice 0177 adds a service-scoped AG detail/debug endpoint for one persisted CX
retrieval package:

```text
GET /admin/v1/operations/retrieval-packages/{retrieval_package_id}
```

Implemented:

- retrieval package store `get_retrieval_package()` port
- SQLAlchemy read adapter for package header plus `cx_retrieval_evidence_items`
- `ag_retrieval_package_detail_projection.v1`
- safe evidence metadata projection for rank, citation, anchor, hashes, scores,
  permission summary, neighbor count, quality flags, and score range
- OpenAPI path registration for retrieval package list/detail endpoints
- regression coverage for auth/filter/problem responses, not-found handling,
  SQL detail reads, and redaction

## Safety

The detail projection intentionally omits `evidence_text_preview`, raw source
text, vector payloads, storage paths, and principal ids. Operators get hashes,
bounded package metadata, score metadata, permission outcome summaries, and
trace/request correlation for debugging without turning AG into a document text
exfiltration surface.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_retrieval_operations.py tests/test_nex_ag_operations.py
```

Observed result:

```text
147 passed, 1 warning
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1377 passed, 1 warning
statement_coverage=98.07% threshold=95.00%
branch_coverage=93.57% threshold=85.00%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
```
