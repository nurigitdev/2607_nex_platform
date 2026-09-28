# Slice 1029: AE Runtime Policy Contract, OpenAPI, and Observability

## Goal

Freeze the S103 intent, resolved runtime-policy, generation-package, chat
lineage, and operational-event surfaces as privacy-safe public contracts.

## Implementation

- Added strict canonical schemas for AE intent decisions, resolved runtime
  policies, and CX generation-policy packages.
- Added indexed positive fixtures and negative raw-prompt, raw-evidence, and
  provider-runtime leakage fixtures.
- Extended the canonical chat interaction schema for completed and policy-only
  pending/no-answer/failure lineage.
- Promoted AE OpenAPI to `1.1.0` and documented the runtime-policy catalog,
  resolver, and safe prompt-binding routes with named schemas.
- Promoted workspace-chat operational events to v2 with execution mode,
  compatibility-rule, policy, prompt-binding, and generation-package hashes.
  Prompt/response content, owner identity, retrieval identifiers, and provider
  runtime remain excluded.

## Decisions

- Canonical JSON Schemas are stricter than the projection-oriented OpenAPI
  summaries and remain the validation authority.
- Operational events contain stable policy metadata and hashes only.
- No database migration, PostgreSQL access, or remote provider is required in
  this Slice. Actual PostgreSQL evidence follows in Slice 1030.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_runtime_policy_contracts.py \
  --test tests/test_nex_ae_workspace_chat_observability.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace_chat_observability.py \
  --smoke scripts/smoke/run_ae_runtime_policy_contract_observability.py
```

## Observed Evidence

- Slice Gate: PASS (`2081 passed`; statement `97.87%`, branch `95.65%`).
- Workspace-chat observability target coverage: statement/branch `100.00%`.
- Contract validation: PASS (`96` schemas, `150` examples, `113` negative
  examples, `7` OpenAPI documents).
- Contract/observability smoke: PASS (`12/12` checks), next Slice `1030`.
- AE contract/API drift improved from `36` to `33`; all three runtime-policy
  runtime operations are now represented in OpenAPI.
