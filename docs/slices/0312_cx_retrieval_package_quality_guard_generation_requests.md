# Slice 0312: CX Retrieval Package Quality Guard for Generation Requests

## Scope

Add a CX admission guard that checks retrieval package quality before a grounded
generation request can call MO.

This slice does not change external API routes, database schema, remote provider
configuration, or retrieval package persistence. It tightens the internal
generation boundary created in Slice 0311.

## Implemented

- Added `cx_retrieval_package_quality_guard.v1`.
- Added `retrieval_package_quality` as the last grounded generation boundary
  stage before MO invocation.
- Added `build_retrieval_package_quality_guard` and
  `validate_retrieval_package_quality`.
- Blocked READY packages that are internally inconsistent:
  - missing or invalid `score_summary`;
  - missing evidence items;
  - `LOW_CONFIDENCE` or `NO_ANSWER` confidence bucket;
  - non-empty no-answer reason;
  - blocking quality flags such as `source_unavailable` or `stale_embedding`;
  - best score below the effective low-confidence threshold;
  - missing or empty source summary counts.
- Resolved low-confidence threshold in this order:
  1. `score_summary.low_confidence_threshold`;
  2. `retrieval_profile.confidence_policy.low_confidence_threshold`;
  3. default `0.2`.
- Kept tokenizer fallback warnings non-blocking. The guard records warning kinds
  without document ids or raw text.
- Kept the audit raw-safe by recording `no_answer_reason_present` instead of the
  raw no-answer reason value.

## Runtime Behavior

If the guard fails, CX returns:

```text
status_code=409
error_code=cx.retrieval_package_quality_blocked
failed_stage=retrieval_package_quality
```

The request is blocked before `build_mo_generation_payload` and before the MO
generation client is called.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_cx_generation.py -q`
- Downstream route regression:
  `./.venv/bin/pytest tests/test_nex_cx_generation.py tests/test_nex_cx_drafts.py tests/test_nex_cx_progress.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed targeted result:

```text
43 passed, 1 warning
```

Observed downstream route result:

```text
57 passed, 1 warning
```

Observed full quality gate:

```text
2154 passed, 1 warning
statement_coverage=98.50% threshold=95.00%
branch_coverage=95.28% threshold=85.00%
contract_validation=pass schemas=50 examples=81 negative_examples=56 openapi=7
```
