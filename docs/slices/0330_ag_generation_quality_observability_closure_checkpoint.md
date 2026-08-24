# Slice 0330: AG Generation Quality Observability Closure Checkpoint

## Scope

Close the S33 AG generation quality observability sequence that started at
Slice 0321.

The goal of this checkpoint is not to add a new runtime capability. It records
that the AG side now has a traceable path from grounded generation quality gaps
to dashboard attention, issue candidates, operator detail/runbook, contract
fixtures, and actual PostgreSQL smoke evidence.

## Closure Map

| Slice | Closure Role |
| --- | --- |
| 0321 | AG grounded response quality gap audit foundation. |
| 0322 | Quality projection wiring into generation audit projection. |
| 0323 | Grounded quality projection schema and examples. |
| 0324 | Operations dashboard generation quality surface and issue candidate. |
| 0325 | PostgreSQL smoke for AG generation quality dashboard/issue candidate. |
| 0326 | Operator issue detail/runbook projection. |
| 0327 | Read-only API route for issue detail projection. |
| 0328 | Issue detail schema, examples, negative redaction fixture, OpenAPI wiring. |
| 0329 | Actual `nex_ag_test` smoke evidence for issue detail contract/runbook. |

## Implemented

- Added a lightweight closure guard test that verifies:
  - Slice 0321-0329 docs are linked from `docs/README.md`;
  - the grounded quality and issue-detail schemas exist;
  - the protected PostgreSQL smoke runner retains issue-detail contract/runbook
    checks.
- Marked Slice 0330 as the S33 closure checkpoint in `docs/README.md`.

## Operational State

The current AG generation quality observability path is:

```text
CX/AE generation audit sources
-> ag_generation_audit_projection.v1
-> ag_generation_audit_grounded_response_quality_projection.v1
-> ag_generation_quality_dashboard_section.v1
-> generation_quality_attention_required.v1
-> ag_generation_quality_issue_detail_projection.v1
-> protected nex_ag_test PostgreSQL smoke evidence
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_contract_validation.py -q
23 passed
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2218 passed, 1 warning
statement_coverage=98.55%
branch_coverage=95.48%
contract_validation=pass schemas=52 examples=84 negative_examples=61 openapi=7
```
