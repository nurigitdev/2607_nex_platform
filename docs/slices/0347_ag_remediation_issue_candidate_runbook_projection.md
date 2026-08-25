# Slice 0347: AG Remediation Issue Candidate Runbook Projection

## Scope

Promote active or failed AG generation remediation tasks into the protected
operations issue-candidate projection with stable runbook identifiers and task
detail links for operators.

## Implemented

- Added `generation_remediation_attention_required.v1` to the operations issue
  candidate rule catalog.
- Wired remediation task stores into the `/admin/v1/operations/issue-candidates`
  projection path.
- Added generation remediation issue candidate projection from the dashboard
  `generation_remediation.attention` section.
- Added remediation runbook ids, recommended operator actions, task ids,
  generation ids, status counts, and task detail paths to the candidate signal.
- Updated the operations issue candidate example to include current generation
  quality and remediation rule catalog entries.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_operations.py -q
157 passed
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=56 examples=88 negative_examples=65 openapi=7
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2390 passed
statement_coverage=98.54%
branch_coverage=95.68%
```

Next slices:

```text
Slice 0348: AG remediation detail API/contract hardening
Slice 0349: AG remediation dashboard PostgreSQL smoke evidence
Slice 0350: S35 remediation observability closure checkpoint
```
