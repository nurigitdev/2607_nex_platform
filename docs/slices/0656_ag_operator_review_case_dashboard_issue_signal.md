# Slice 0656: AG operator review case dashboard issue signal

## Scope

- Extends the AG operations dashboard `operator_review_cases` section with
  case queue, workbench detail, and timeline entrypoints.
- Adds `operator_review_case_attention_required.v1` to operations issue
  candidates so case lifecycle attention is tracked separately from workbench
  target attention.
- Wires `operator_review_case_store` through
  `/admin/v1/operations/issue-candidates`.
- Updates the operations projection schema and dashboard success fixture for the
  new case workbench fields.

## Boundary

- No new database table or migration.
- The dashboard still reuses `ag_op_cases`.
- Issue signals include only metadata-safe case IDs, target refs, reason codes,
  links, runbook IDs, and recommended action IDs.
- Raw case comments, action comments, resolution text, source text, prompts,
  storage paths, database URLs, and idempotency keys remain excluded.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operations.py tests/test_nex_ag_operations.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Targeted result:

```text
166 passed, 1 warning
nex_ag.operations coverage: 98%
```

## Next

- Slice 0657 should freeze the queue/detail/timeline contract and OpenAPI
  surface.
