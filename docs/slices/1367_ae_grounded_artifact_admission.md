# Slice 1367: AE Grounded Artifact Admission

## Goal

Connect the verified AE generated-response lineage to owner-scoped artifact
creation and durable asynchronous rendering without copying generated content,
private evidence, or storage references into the render queue.

## Implementation

- Added an owner-scoped generated-response artifact admission route that
  creates the artifact and admits its render job as one idempotent workflow.
- Grounded artifacts now require the S1366 CX grounding lineage and verify the
  retrieval package ID/hash, evidence count, citation status, and privacy flags
  against the artifact source handoff before persistence.
- Cross-owner handoffs remain hidden behind a `404` boundary.
- Render queue payloads contain response and source metadata only; generated
  text, content hashes, private evidence, and storage references are excluded.
- Existing artifact-only and synchronous compatibility routes remain intact.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_grounded_artifact_admission.py \
  --test tests/test_ae_async_artifact_response_lineage.py \
  --test tests/test_ae_async_artifact_rendering.py \
  --test tests/test_ae_async_artifact_render_admission.py \
  --coverage-target scripts/smoke/run_ae_grounded_artifact_admission.py \
  --smoke scripts/smoke/run_ae_grounded_artifact_admission.py
```

Protected PostgreSQL and live-provider evidence remains assigned to Slice
1370. Slice 1368 hardens restart recovery, cancellation, preview/download, and
owner isolation for this admitted lifecycle.

Observed evidence:

- focused grounded admission and async rendering regression: `113 passed`
- Slice Gate: `2,866 passed`, `5 skipped`
- statement coverage: `98.32%`; branch coverage: `96.21%`
- evidence runner coverage: `100%` statement/branch
- contract validation: `162` schemas, `221` examples, `189` negative examples,
  and `7` OpenAPI documents
- deterministic admission evidence: `8/8` checks
