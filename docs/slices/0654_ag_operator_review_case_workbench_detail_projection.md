# Slice 0654: AG Operator Review Case Workbench Detail Projection

Slice 0654 adds a metadata-safe case workbench detail projection for the
operator review case queue.

## Scope

- Adds `GET /admin/v1/operator-review/cases/{case_id}/workbench-detail`.
- Adds `ag_operator_review_case_workbench_detail.v1`.
- Reuses `ag_op_cases`; no new table or migration is added.
- Shapes a case detail for operator screens from the existing case record and
  queue item:
  - safe target/operator/assignment/source refs
  - attention status and recommended actions
  - latest safe action summary
  - resolution hash plus bounded preview
  - available and blocked action controls for the current case status
  - planned timeline path for the later operational-event correlation slice
- Keeps raw comments, prompts, generated output, source text, storage paths,
  metadata payloads, and idempotency keys out of the detail payload.

## Decision

- The existing `GET /admin/v1/operator-review/cases/{case_id}` remains the
  canonical case record read. The new workbench detail route is a UI/debug
  projection with stricter redaction and action affordance metadata.
- Action history remains operational-events-first; inline event expansion is
  deferred to the timeline/evidence correlation slice.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
