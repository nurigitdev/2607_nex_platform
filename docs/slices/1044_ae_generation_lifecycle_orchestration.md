# Slice 1044: AE Generation Lifecycle Orchestration

## Goal

Add a route-independent AE service that reconciles durable CX asynchronous job
and handoff state into the S105 progress contract.

## Implementation

- Added an owner-bound lifecycle orchestrator that reads the tenant and owner
  context from an already-authorized AE chat record.
- Non-terminal interactions poll only the durable CX job projection.
- Terminal CX jobs poll handoff once to converge `READY` or `BLOCKED` state.
- Completed and blocked AE records use their immutable local projection unless
  an explicit force refresh is requested.
- Handoff content is used only for integrity validation and is discarded before
  the orchestration result is returned.
- CX transport and lower-level contract failures are normalized into stable AE
  lifecycle errors.

## Decisions

- The service does not persist records or expose an HTTP route; those concerns
  remain in following Slices.
- A completed local lifecycle is cacheable because CX terminal job states are
  immutable.
- Owner IDs, raw content, provider runtime, and credentials are absent from the
  returned progress projection.
- No database migration, PostgreSQL access, or remote provider is required.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_generation_lifecycle.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generation_lifecycle.py
```

## Observed Evidence

- Focused regression: `16 passed`.
- Slice Gate: `2274 passed`, `1 skipped` protected PostgreSQL smoke.
- Repository coverage: statement `97.92%`, branch `95.77%`.
- Target module coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `98` schemas, `153` examples, `116` negative
  examples, and `7` OpenAPI documents passed.
