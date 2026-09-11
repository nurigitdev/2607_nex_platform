# Slice 0671: AG operator review case decision lifecycle boundary audit

## Intent

Start S68 by freezing the AG-owned operator review case decision lifecycle
boundary after S67 evidence/admission closure.

## Scope

- Add
  `scripts/smoke/run_ag_operator_review_case_decision_lifecycle_boundary_audit.py`.
- Confirm S68 starts after the closed S67 evidence/admission loop.
- Confirm Slice 0671 adds no database table.
- Confirm lifecycle projections reuse existing AG-owned sources:
  - `ag_op_cases`
  - `service_operational_events`
  - `ag_op_notes`
  - `ag_ev_exports`
- Confirm action mutation remains authoritative at
  `POST /admin/v1/operator-review/cases/{case_id}/actions`.
- Confirm action history remains operational-events-first.
- Confirm closure packets start as read-model payloads, not as a new persistence
  table.

## Decision

- `nex-ag` owns the decision lifecycle projection.
- The first implementation step after this audit is case action timeline
  projection hardening.
- Lifecycle read models should derive from existing case rows, latest-action
  metadata, and safe operational events.
- Closure packets should summarize safe case, note, export, and action evidence
  without storing raw operator text, raw evidence bodies, prompts, source text,
  provider payloads, storage paths, database URLs, service tokens, idempotency
  keys, or raw metadata payloads.
- A dedicated lifecycle/closure table is deferred until query or retention
  requirements prove it is necessary.
- PostgreSQL smoke evidence for the lifecycle path must use the real
  `nex_ag_test` database before S68 closure.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_case_decision_lifecycle_boundary_audit.py tests/test_ag_operator_review_case_decision_lifecycle_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_case_decision_lifecycle_boundary_audit.py -q --cov=run_ag_operator_review_case_decision_lifecycle_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_case_decision_lifecycle_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
ag_operator_review_case_decision_lifecycle_boundary_audit=pass paths=20/20 tokens=35/35 token_groups=6/6 tables=4/4 boundary=ag_owned_operator_review_case_decision_lifecycle history=operational_events_first closure=read_model_first next=Slice_0672
```
