# Slice 0568: AG daemon supervisor route wiring

## Scope

Expose the AE scheduler daemon supervisor read model through AG admin
operations routes.

## Implementation

- Added the AG read-only supervisor collection route:
  `/admin/v1/operations/artifact-retention/scheduler-daemon-supervisor-results`.
- Added the AG read-only supervisor detail route:
  `/admin/v1/operations/artifact-retention/scheduler-daemon-supervisor-results/{id}`.
- Added query validation for supervisor `action`, `result_status`, and `limit`.
- Routed AE source errors through the existing AG artifact operations problem
  response path.
- Added route regression coverage for successful collection/detail reads,
  authorization, service filter guardrails, invalid filters, missing detail,
  and AE source failure.

## Guardrails

- The AG routes are read-only projections over AE-owned APIs.
- AG does not write AE daemon supervisor rows, enqueue AE retention jobs, or
  control AE daemon processes.
- Raw supervisor command/result payloads, database URLs, local storage paths,
  raw artifact payloads, and raw execution payloads remain excluded from AG
  responses.
- No protected PostgreSQL smoke is added in this slice; the next smoke slice
  should prove this AG route against the real AE test database boundary.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
```

Results:

- Targeted AG artifact operations regression: `73 passed`.
- `nex_ag.artifact_operations` targeted coverage: `98%`.

## Next

- Slice 0569 should add protected PostgreSQL smoke evidence for the AG
  supervisor read-model route against `NEX_AE_TEST_DATABASE_URL`.
