# Slice 1047: AE Generation Recovery and Retry Orchestration

## Goal

Expose a read-only recovery decision and require eligible, lineage-preserving
child admission for retries.

## Implementation

- Added `GET /api/v1/chat/interactions/{interaction_id}/recovery` with the same
  owner-scoped CX reconciliation used by progress polling.
- Added a retry preparation service that validates recovery eligibility, a new
  interaction ID, matching input hash, and generation request shape.
- Forced eligible retries to asynchronous execution and produced canonical
  parent job/generation lineage.
- Refactored the existing retry route to consume the prepared payload and
  lineage before child admission.
- Kept the recovery response read-only and free of prompt or generated content.

## Decisions

- Recovery planning does not mutate lifecycle state beyond persisting a newer
  canonical CX projection discovered during polling.
- Retry remains an explicit child interaction; in-place job replay is not
  allowed.
- No database migration, PostgreSQL access, or remote provider is required.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_generation_recovery_orchestration.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generation_recovery.py
```

## Observed Evidence

- Focused recovery and compatibility regression: `21 passed`; focused target
  coverage hardening: `13 passed`.
- Slice Gate: `2298 passed`, `1 skipped` protected PostgreSQL smoke.
- Repository coverage: statement `97.90%`, branch `95.76%`.
- Recovery orchestration module coverage: statement `100.00%`, branch
  `100.00%`.
- Contract validation: `98` schemas, `153` examples, `116` negative
  examples, and `7` OpenAPI documents passed.
