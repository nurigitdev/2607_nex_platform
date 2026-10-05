# Slice 1368: AE Grounded Artifact Recovery And Access

## Goal

Harden preview/download, cancellation, restart recovery, and owner isolation for
the grounded artifact lifecycle admitted by Slice 1367.

## Implementation

- Unified artifact-file metadata, preview, and download routes on the AE facade
  authentication boundary while retaining service-token compatibility.
- Added durable artifact lookup by file ID for both in-memory and SQLAlchemy
  stores; orphaned file metadata is not publicly resolvable.
- Browser owner projections redact private `storage_ref` values while keeping
  the existing service-facing metadata contract compatible.
- Cross-owner file, preview, download, status, cancellation, and recovery
  requests fail behind the same `404` boundary.
- A fresh AE application runtime can reuse durable artifact/queue state and
  recover cancelled render status plus owner-safe preview and download links.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_grounded_artifact_recovery_evidence.py \
  --test tests/test_ae_grounded_artifact_recovery_access.py \
  --test tests/test_ae_async_artifact_render_recovery.py \
  --test tests/test_ae_async_artifact_rendering.py \
  --test tests/test_nex_ae_artifacts.py \
  --coverage-target scripts/smoke/run_ae_grounded_artifact_recovery_access.py \
  --smoke scripts/smoke/run_ae_grounded_artifact_recovery_access.py
```

Actual PostgreSQL restart and private-file persistence evidence remains assigned
to Slice 1370. Slice 1369 adds the canonical contract and deterministic
cross-service operations evidence.

Observed evidence:

- focused artifact access/recovery regression: `272 passed`
- Slice Gate: `2,872 passed`, `5 skipped`
- statement coverage: `98.31%`; branch coverage: `96.18%`
- evidence runner coverage: `100%` statement/branch
- contract validation: `162` schemas, `221` examples, `189` negative examples,
  and `7` OpenAPI documents
- deterministic recovery/access evidence: `8/8` checks
