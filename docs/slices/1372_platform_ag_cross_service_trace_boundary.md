# Slice 1372: Platform AG Cross-Service Trace Boundary

## Goal

Freeze S138 before implementation so AG reconstructs the golden journey through
redacted service APIs without taking ownership of service data.

## Decision

- Eight integration gaps are assigned to Slices 1373 through 1380.
- AG source APIs require `service:call` plus `operations:read` and ADMIN route
  admission.
- The protected evidence in Slice 1380 requires actual service test databases;
  remote model providers are not called again merely to build the timeline.
- Quarantined legacy PostgreSQL projection adapters remain unavailable to
  managed profiles and are removed from the S138 target path.
- S138 closes in Slice 1381 after contracts, runbook, and Full Gate evidence.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --test tests/test_platform_ag_cross_service_trace_boundary.py \
  --coverage-target scripts/smoke/run_platform_ag_cross_service_trace_boundary.py
```

The boundary audit must report `BOUNDARY_FROZEN`, eight open integration gaps,
and `next=1373`.

Observed evidence:

- Slice Gate (`nex-ag`): `2,459 passed`.
- Repository statement coverage: `98.87%`.
- Repository branch coverage: `96.46%`.
- Boundary audit statement/branch coverage: `100%`/`100%`.
- Contract validation: `163` schemas, `222` examples, `190` negative
  examples, and `7` OpenAPI documents.
- No database or remote provider was contacted.
