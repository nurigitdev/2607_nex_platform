# Slice 0346: AG Remediation Operations Dashboard Projection

## Scope

Surface persisted AG generation remediation tasks in the protected operations
dashboard so operators can see active repair work beside generation quality,
retrieval, processing, job, event, and log signals.

## Implemented

- Added `list_recent()` to the remediation task stores.
- Wired the `nex-ag` app so remediation task APIs and the operations dashboard
  share the same store.
- Added `generation_remediation` to
  `ag_operations_dashboard_snapshot_projection.v1`.
- Added remediation dashboard summary, recent items, attention items, and
  source status reporting.
- Extended the operations projection contract and dashboard example.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_ag_generation_remediation.py -q
202 passed
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=56 examples=88 negative_examples=65 openapi=7
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2389 passed
statement_coverage=98.53%
branch_coverage=95.67%
```

Next slices:

```text
Slice 0347: AG remediation issue candidate/runbook projection
Slice 0348: AG remediation detail API/contract hardening
Slice 0349: AG remediation dashboard PostgreSQL smoke evidence
Slice 0350: S35 remediation observability closure checkpoint
```
