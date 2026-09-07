# Slice 0577: AG supervised process route wiring

## Scope

Expose AG's supervised process read model through protected read-only admin
routes.

## Implementation

- Added AG admin collection route:
  `/admin/v1/operations/artifact-retention/scheduler-daemon-process-snapshots`.
- Added AG admin detail route:
  `/admin/v1/operations/artifact-retention/scheduler-daemon-process-snapshots/{daemon_supervised_process_record_id}`.
- Added query validation for `scheduler_id`, supervisor-style `action`,
  supervised `process_status`, and collection `limit`.
- Wired route handlers to the AE artifact operations client and the Slice 0576
  projection builders.
- Added route regression coverage for successful collection/detail responses,
  auth failure, invalid service filter, invalid action, invalid process status,
  invalid limit, missing detail, and AE source failure.

## Guardrails

- The new routes are read-only AG projections.
- AE remains the system of record for process snapshot/event persistence.
- AG still cannot write AE tables, enqueue AE jobs, start or stop AE
  subprocesses, or receive raw process/runtime payloads.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
```

Targeted AG artifact operations coverage: 77 passed, statement/branch combined
module coverage 97%.

## Next

- Slice 0578 should add protected PostgreSQL smoke evidence that writes AE
  process snapshot evidence through AE APIs and reads it back through the AG
  admin routes.
