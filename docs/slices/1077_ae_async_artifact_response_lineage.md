# Slice 1077: AE Asynchronous Artifact Response Lineage

## Goal

Bind asynchronous artifact rendering to the durable generated-response lineage
closed by S107 without copying response content or storage references into the
render queue.

## Changes

- Added exact-owner lookup of the canonical chat interaction before admitting
  an async render request that supplies `response_id`.
- Validated response, interaction, workspace, chat-document, CX-generation,
  and structured-draft lineage against the persisted artifact source.
- Added fail-closed handling for missing, pending, corrupt, mismatched, and
  temporarily unavailable response lineage.
- Kept the queue payload content-free; only the verified `response_id` remains
  in the immutable render request.

## Decisions

- `ae_chat_interactions.generation_summary` remains the response-lineage source
  of truth, so no new response or artifact-lineage table is introduced.
- `response_id` remains optional for compatibility with existing artifact-only
  clients. When supplied, lineage validation is mandatory.
- Cross-owner and missing responses share a `404` boundary. Persisted lineage
  corruption and store outages fail closed without exposing private details.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_artifact_response_lineage.py \
  --test tests/test_ae_async_artifact_rendering.py \
  --test tests/test_ae_async_artifact_render_admission.py \
  --test tests/test_nex_ae_artifacts.py \
  --coverage-target services/nex-ae-api/nex_ae_api/async_artifact_rendering.py
```

Observed evidence:

- Slice Gate: `PASS` (`199` selected regression tests)
- Overall statement coverage: `98.04%`
- Overall branch coverage: `96.05%`
- `async_artifact_rendering.py` statement coverage: `99.40%`
- `async_artifact_rendering.py` branch coverage: `98.57%`
