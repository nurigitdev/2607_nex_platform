# Slice 0996: CX AE Generation Handoff Projection

## Goal

Provide one owner-scoped polling projection that joins a durable asynchronous
generation job with its persisted generation metadata and private result.

## Implementation

- Added `cx_generation_handoff.v1` with `PENDING`, `READY`, and `BLOCKED`
  states and deterministic next actions.
- Added `GET /api/v1/generation-jobs/{job_id}/handoff` under the existing AE to
  CX service-token and tenant/subject authorization boundary.
- Active jobs expose metadata only; failed and cancelled jobs expose only the
  allowlisted safe error projection.
- Successful jobs fail retryably until the persisted generation read model and
  owner-private content are both available and internally consistent.
- Production bootstrap injects the existing restart-safe generation read model;
  no new table, storage path, or provider call is introduced.

## Verification

```bash
scripts/quality/run_checkpoint_gate.sh --service nex-cx \
  --test tests/test_nex_cx_generation_handoff.py \
  --test tests/test_nex_cx_async_generation_operations.py \
  --test tests/test_cx_mvp_integration_ae_handoff_boundary_audit.py \
  --coverage-target services/nex-cx/nex_cx/generation_handoff.py \
  --coverage-target services/nex-cx/nex_cx/async_generation_operations.py \
  --smoke scripts/smoke/run_cx_mvp_integration_ae_handoff_boundary_audit.py
```

## Observed Evidence

- Checkpoint Gate: `7,394 passed`.
- Repository statement coverage: `98.64%`.
- Repository branch coverage: `96.51%`.
- Generation handoff and async operations statement/branch coverage:
  `100%`/`100%` each.
- Contract validation: `91` schemas, `142` positive examples, `107` negative
  examples, and `7` OpenAPI documents.
- Boundary audit: resolved gaps `4/8`, next Slice `0997`.
