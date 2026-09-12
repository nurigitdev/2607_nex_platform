# Slice 0680: S68 operator review case decision lifecycle closure

## Intent

Close the S68 operator review case decision lifecycle slice family after timeline,
action outcome, assignment workload, closure packet, dashboard, contract, and
PostgreSQL smoke evidence are in place.

## Scope

- Add `scripts/smoke/run_s68_operator_review_case_decision_lifecycle_closure.py`.
- Verify S68 required files from Slice 0671 through Slice 0680.
- Verify lifecycle schema versions, closure packet route, dashboard workload
  integration, OpenAPI route documentation, quality gate hooks, and protected
  PostgreSQL smoke coverage.
- Keep the lifecycle boundary read-model-only over existing AG-owned tables.

## Decision

S68 is closed without adding a lifecycle or closure packet persistence table.
The decision lifecycle uses:

- `ag_op_cases`
- `service_operational_events`
- `ag_op_notes`
- `ag_ev_exports`

Closure packets remain read-model payloads and are not persisted. PostgreSQL
evidence is protected by explicit opt-in and uses the real `nex_ag_test`
database when enabled.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_s68_operator_review_case_decision_lifecycle_closure.py tests/test_s68_operator_review_case_decision_lifecycle_closure.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_s68_operator_review_case_decision_lifecycle_closure.py -q --cov=run_s68_operator_review_case_decision_lifecycle_closure --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_s68_operator_review_case_decision_lifecycle_closure.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
s68_operator_review_case_decision_lifecycle_closure=pass slice_range=0671-0680 required_files=28 boundary=ag_owned_operator_review_case_decision_lifecycle closure_packet_storage=read_model_only_not_persisted smoke=test_db_protected
```
