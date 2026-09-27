# Slice 1019: AE Workspace Chat Contract, OpenAPI, and Observability

## Goal

Align the public AE workspace/chat contracts with the durable S102 runtime and
record state transitions without exposing private prompt, response, owner, or
provider content.

## Implementation

- Hardened `ae_chat_interaction.v1` with workspace lineage, owner fields,
  `PENDING`, and the generic execution-failure shape used by durable
  orchestration.
- Added the strict `ae_workspace_activity.v1` schema, positive fixtures for
  pending chat/activity state, and a negative raw-prompt leakage fixture.
- Promoted the AE OpenAPI document to `1.0.0` and bound workspace, activity,
  and chat routes to named request/response schemas that point to the canonical
  JSON Schemas.
- Added idempotent `ae.workspace_chat.state_changed` operational events for
  pending and terminal states. The events contain state and counts only;
  prompt/response content, owner identity, provider detail, and retrieval
  identifiers are excluded.
- Event persistence is non-blocking: operational-event store failure does not
  alter the chat API result.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_workspace_chat_contracts.py \
  --test tests/test_nex_ae_workspace_chat_observability.py \
  --test tests/test_ae_workspace_chat_contract_observability.py \
  --test tests/test_ae_contract_api_drift_audit.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace_chat_observability.py \
  --smoke scripts/smoke/run_ae_workspace_chat_contract_observability.py
```

The smoke is deterministic and does not require PostgreSQL or a remote model
provider. Actual `nex_ae_test` persistence evidence remains Slice 1020.

## Observed Evidence

- Contract validation: `93` schemas, `147` positive examples, `110` negative
  examples, and `7` OpenAPI documents.
- Deterministic smoke: `12/12` checks and two redacted lifecycle events.
- Slice Gate: `1980 passed`; statement coverage `97.75%`, branch coverage
  `95.56%`.
- Target coverage: workspace/chat observability statement/branch `100%`/`100%`;
  chat runtime statement `97.62%`, branch `98.78%`.
