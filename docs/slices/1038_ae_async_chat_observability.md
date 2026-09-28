# Slice 1038: AE Asynchronous Chat Observability

## Goal

Expose asynchronous chat lifecycle progress through workspace activity and
operational events without copying owner-private input, generated content, or
provider details.

## Implementation

- Upgraded AE workspace-chat observability to `v3` with asynchronous lifecycle,
  job, handoff, attempt, retryability, error-code, and retry-lineage presence
  metadata.
- Strengthened event identity so repeated `PENDING` records remain idempotent
  while distinct CX job states and attempts produce distinct events.
- Added workspace activities for asynchronous admission, refresh, and
  cancellation.
- Added a persisted-record activity adapter so refresh and cancel routes can
  append owner-workspace history without reconstructing raw chat input.
- Kept prompt text, generated response content, owner identity, provider
  details, job identifiers, and retry parent identifiers out of all new
  observability payloads.
- Normalized in-memory and SQL workspace activity failures into the existing AE
  problem-response boundary.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_workspace_chat_observability.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace_chat_observability.py
```

Focused tests additionally cover workspace activity orchestration and the
async admission, refresh, cancellation, and retry routes. No database or
remote provider is required for this Slice.

## Observed Evidence

- Focused observability, workspace activity, and async route tests: `39 passed`
  with one known warning.
- Slice Gate: `2209 passed` with one known warning.
- Repository statement coverage: `97.89%`.
- Repository branch coverage: `95.71%`.
- Workspace-chat observability statement/branch coverage: `100%`/`100%`.
- Contract validation: 96 schemas, 150 positive examples, 113 negative
  examples, and 7 OpenAPI documents.
