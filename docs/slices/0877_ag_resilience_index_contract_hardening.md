# Slice 0877: AG resilience index and contract hardening

## Goal

Freeze the deterministic bounded-read indexes, pagination envelope, protected
resilience operations API, and privacy constraints before live load evidence.

## Implementation

- Added three short PostgreSQL index names for event-type, trace, and evidence
  export reads. Every index includes the timestamp and stable identity tie-breaker.
- Unified SQL evidence-export ordering with the in-memory implementation as
  `updated_at DESC, export_id DESC`.
- Made audit action pagination required in the dedicated and dashboard schemas.
- Added a strict resilience-performance JSON Schema, positive example, and a
  negative database-URL leak fixture.
- Added the protected resilience route and audit cursor to OpenAPI, including
  timeout, pagination, admission, pool, and privacy shapes.
- No table was introduced.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_resilience_performance_contracts.py \
  tests/test_nex_ag_resilience_performance_operations.py \
  tests/test_nex_ag_audit_evidence_contracts.py \
  tests/test_nex_ag_audit_evidence_operations.py \
  tests/test_nex_ag_operator_review_exports.py

./.venv/bin/python scripts/quality/validate_contracts.py contracts
```

Observed verification:

```text
focused contract/index/export tests: 87 passed
contract validation: schemas=80 examples=130 negative_examples=93 openapi=7
aggregate regression: 5981 passed, 1 known warning
statement=73237/74118=98.811354866564%
branch=17186/17836=96.355685131195%
```
