# Slice 0348: AG Remediation Detail API Contract Hardening

## Scope

Harden the AG generation remediation task detail API so operators receive a
stable redacted detail projection with runbook, transition, and debug metadata.

## Implemented

- Added `ag_generation_remediation_task_detail.v1`.
- Changed the remediation task `GET` route to return a detail projection instead
  of a bare action record.
- Preserved create, list, and status update response shapes.
- Added runbook selection for failed, waiting-on-CX, prompt-policy-review,
  urgent, active, completed, and cancelled remediation tasks.
- Added allowed next status, debug path, and redaction summary fields.
- Updated the AG OpenAPI contract and added a validating example.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation.py -q
53 passed
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=57 examples=89 negative_examples=65 openapi=7
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2397 passed
statement_coverage=98.54%
branch_coverage=95.69%
```

Next slices:

```text
Slice 0349: AG remediation dashboard PostgreSQL smoke evidence
Slice 0350: S35 remediation observability closure checkpoint
```
