# Slice 1369: Platform Grounded Generation Artifact Deterministic E2E

## Goal

Publish the AE grounded-artifact admission contract and compose the completed
CX generation, citation repair, AE response lineage, artifact admission, and
restart recovery evidence into one deterministic cross-service checkpoint.

## Implementation

- Added the strict `ae_grounded_artifact_admission.v1` response contract with
  owner-scoped response binding, validated citation workflow, content-free
  render admission, and an indexed negative privacy fixture.
- Registered `POST /api/v1/generated-responses/{response_id}/artifacts` in AE
  OpenAPI with browser/service authentication, idempotency, response, denial,
  and dependency failure semantics.
- Aligned the canonical artifact render-job contract with runtime `QUEUED`,
  `FAILED`, and `CANCELLED` stages plus optional durable timestamps.
- Added a deterministic evidence runner that composes S137 Slices 1364-1368
  and reports four explicit scenarios: success, bounded repair, denial, and
  restart recovery.
- The evidence pack contains only statuses, counts, hashes, IDs, and booleans;
  it does not retain prompts, generated text, evidence text, storage refs, or
  provider/database secrets.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_grounded_artifact_contracts.py \
  --test tests/test_platform_grounded_generation_artifact_e2e.py \
  --test tests/test_ae_async_artifact_response_lineage.py \
  --test tests/test_ae_grounded_artifact_recovery_access.py \
  --test tests/test_ae_async_artifact_render_contracts.py \
  --coverage-target scripts/smoke/run_platform_grounded_generation_artifact_e2e.py \
  --smoke scripts/smoke/run_platform_grounded_generation_artifact_e2e.py
```

Observed evidence:

- focused grounded-artifact contract and E2E regression: `41 passed`
- OpenAPI version regression after preserving the existing `1.7.0` profile:
  `50 passed`
- Slice Gate: `2,882 passed`, `5 skipped`
- statement coverage: `98.32%`; branch coverage: `96.19%`
- deterministic E2E runner coverage: `100%` statement/branch
- contract validation: `163` schemas, `222` examples, `190` negative
  examples, and `7` OpenAPI documents
- deterministic evidence: `12/12` checks, `5/5` components, and `4/4`
  success/repair/denial/recovery scenarios

Actual PostgreSQL and live generation-provider execution remains exclusively
assigned to Slice 1370.
