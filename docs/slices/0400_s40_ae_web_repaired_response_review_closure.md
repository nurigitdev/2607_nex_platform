# Slice 0400: S40 AE Web Repaired Response Review Closure

## Scope

Close S40 by adding a regression closure check for the AE Web repaired response
review surface, handoff client, decision UX, read-model diagnostics, and
protected PostgreSQL smoke evidence.

## Changes

- Added
  `scripts/smoke/run_s40_ae_web_repaired_response_review_closure.py`.
- Added
  `tests/test_s40_ae_web_repaired_response_review_closure.py`.
- Registered the closure runner in `scripts/quality/run_quality_gate.sh`.
- The closure checks required S40 files, quality-gate smoke hooks, browser-safe
  read-model diagnostics anchors, AE API review/decision contract anchors, live
  PostgreSQL smoke evidence docs, and contiguous `0391-0400` slice docs.

## Notes

This slice does not add a new PostgreSQL write path. The actual test DB smoke
for S40 remains covered by Slice 0396 and Slice 0399 protected smoke evidence.

## Evidence

Closure runner:

```text
./.venv/bin/python scripts/smoke/run_s40_ae_web_repaired_response_review_closure.py --summary
s40_ae_web_repaired_response_review_closure=pass slice_range=0391-0400 required_files=42
```

Targeted regression:

```text
./.venv/bin/pytest tests/test_s40_ae_web_repaired_response_review_closure.py -q --cov=run_s40_ae_web_repaired_response_review_closure --cov-branch --cov-report=term-missing
5 passed
run_s40_ae_web_repaired_response_review_closure.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2890 passed, 1 warning
statement_coverage=98.69%
branch_coverage=96.15%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
s40_ae_web_repaired_response_review_closure=pass slice_range=0391-0400 required_files=42
```
