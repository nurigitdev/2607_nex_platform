# Slice 0631: AG Operator Review Workbench Boundary Audit

Slice 0631 starts S64 by freezing the AG operator review workbench boundary
before adding unified read models, dashboard sections, issue candidates, and
PostgreSQL smoke evidence.

## Scope

- Adds a smoke/audit checkpoint for the AG operator review workbench boundary.
- Confirms S64 builds on the closed S63 `ag_op_notes` and `ag_ev_exports`
  foundations.
- Confirms Slice 0631 adds no new database table.
- Confirms future workbench projections must read safe AG-owned note/export
  records and must not copy raw source payloads, raw notes, raw evidence bodies,
  storage paths, service tokens, provider keys, or idempotency keys.
- Confirms the planned order for Slice 0632 through Slice 0640.

## Decision

- `nex-ag` owns the operator review workbench projection boundary.
- The first implementation step after this audit is a unified read model over
  existing AG-owned note/export records.
- Dashboard wiring and issue-candidate correlation must come after that
  read-model boundary is stable.
- PostgreSQL smoke evidence for the workbench path must use `nex_ag_test`
  before the S64 closure.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_workbench_boundary_audit.py tests/test_ag_operator_review_workbench_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_workbench_boundary_audit.py -q --cov=run_ag_operator_review_workbench_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_workbench_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
ag_operator_review_workbench_boundary_audit=pass paths=17/17 tokens=18/18 token_groups=6/6 tables=2/2 boundary=ag_owned_operator_review_workbench_projection note_table=ag_op_notes export_table=ag_ev_exports next=Slice_0632
```
