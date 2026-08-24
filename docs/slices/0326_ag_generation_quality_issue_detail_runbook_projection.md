# Slice 0326: AG Generation Quality Issue Detail Runbook Projection

## Scope

Add a small AG operator-detail projection for generation quality attention
items surfaced in Slice 0324 and smoke-tested in Slice 0325.

This slice does not introduce a new persistence table. It normalizes an existing
`ag_generation_audit_projection.v1` into a read-only issue detail/runbook shape
so operators can understand why a generation quality item needs attention and
which safe debug paths to open first.

## Implemented

- Added `ag_generation_quality_issue_detail_projection.v1`.
- Added `build_generation_quality_issue_detail_projection`.
- Reused the operations dashboard generation-quality item normalizer so
  dashboard and detail projections do not diverge.
- Added runbook routing for:
  - quality failure triage;
  - missing/unknown quality metadata;
  - warning review;
  - no-attention monitoring;
  - invalid source projection recovery.
- Preserved redaction guarantees: no raw prompt, source text, output text,
  provider endpoint, model path, storage path, or credential-shaped field is
  included.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_operations.py -q
153 passed, 1 warning
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2213 passed, 1 warning
statement_coverage=98.55%
branch_coverage=95.48%
contract_validation=pass schemas=51 examples=83 negative_examples=60 openapi=7
```
