# Slice 0651: AG Operator Review Case Workbench Boundary Audit

Slice 0651 starts S66 by freezing the AG-owned operator review case workbench
boundary before adding queue, detail timeline, evidence linkage, action
admission, contract, and PostgreSQL smoke evidence.

## Scope

- Adds a smoke/audit checkpoint for the AG operator review case workbench loop.
- Confirms S66 builds on the closed S65 case/action foundation and existing
  `ag_op_cases`.
- Confirms Slice 0651 adds no database table.
- Confirms the case queue should read existing AG-owned case records, while
  detail timeline should first read AG `service_operational_events`.
- Keeps action history `operational_events_first`; a dedicated action-history
  table remains deferred until event queries are insufficient.
- Confirms note/export linkage should use safe workbench target refs, operator
  note refs, and redacted evidence export refs.
- Confirms raw notes, evidence bodies, action comments, resolution text,
  prompts, generation output, source text, provider payloads, storage paths,
  database URLs, service tokens, provider keys, and idempotency keys must not
  enter case workbench evidence.
- Confirms the planned order for Slice 0652 through Slice 0660. Slice 0659
  refines this plan to match the implemented order after contract and
  PostgreSQL smoke evidence landed one slice earlier than originally expected.

## Decision

- `nex-ag` owns the case workbench projection.
- The first implementation step after this audit is an operator-facing case
  queue read model.
- The queue should reuse `ag_op_cases` rather than adding a queue table.
- The case timeline should reuse `service_operational_events` rather than
  adding an action event table in S66.
- Evidence linkage is read-model-first and uses only safe refs, hashes,
  bounded previews, and redaction flags.
- PostgreSQL smoke evidence for queue/detail/timeline must use the real
  `nex_ag_test` database before S66 closure.
- The final pre-closure regression should also prove queue/detail/timeline,
  dashboard, and issue-candidate surfaces do not leak raw action comments,
  prompts, source text, storage paths, provider credentials, database URLs, or
  idempotency keys.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_case_workbench_boundary_audit.py tests/test_ag_operator_review_case_workbench_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_case_workbench_boundary_audit.py -q --cov=run_ag_operator_review_case_workbench_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_case_workbench_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
ag_operator_review_case_workbench_boundary_audit=pass paths=17/17 tokens=22/22 token_groups=7/7 tables=4/4 boundary=ag_owned_operator_review_case_workbench_projection case_table=ag_op_cases timeline=service_operational_events next=Slice_0652
```
