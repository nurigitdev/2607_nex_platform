# Slice 0314: AE Chat Generation Quality Rejection Handling

## Scope

Handle CX generation rejections caused by retrieval package readiness or quality
guard failures as safe AE chat interaction records.

This slice does not change database schema, remote provider configuration, or
CX generation admission rules. It keeps non-quality CX/MO generation failures on
the existing problem response path.

## Implemented

- Added `ae_chat_generation_quality_rejection.v1` failure metadata for AE chat.
- Added `build_generation_quality_rejected_chat_interaction_record`.
- Mapped these CX quality rejection codes into persisted AE `FAILED` chat
  records:
  - `cx.retrieval_package_not_ready`;
  - `cx.retrieval_package_quality_blocked`.
- Preserved `retrieval.quality_warnings` on the failed chat record.
- Kept raw CX error detail out of the public chat contract.
- Added a positive quality-rejected chat fixture and a negative raw-detail leak
  fixture.

## Runtime Behavior

When AE has a retrieval package and CX blocks generation because the package is
not ready or fails the retrieval quality guard, AE now returns a normal chat
interaction payload with:

- `status=FAILED`;
- `cx_status=FAILED`;
- `generation=null`;
- `failure.error_code` set to the safe CX quality rejection code;
- `failure.raw_error_detail_included=false`;
- the sanitized retrieval warning contract still present under
  `retrieval.quality_warnings`.

Other CX generation failures, such as provider timeout, continue to return the
existing problem response and are not saved as quality-rejected chat records.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ae_chat.py -q`
- Contract validation:
  `./.venv/bin/pytest tests/test_contract_validation.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed targeted result:

```text
34 passed, 1 warning
```

Observed contract validation result:

```text
21 passed
```

Observed full quality gate:

```text
2161 passed, 1 warning
statement_coverage=98.50% threshold=95.00%
branch_coverage=95.31% threshold=85.00%
contract_validation=pass schemas=50 examples=82 negative_examples=57 openapi=7
```
