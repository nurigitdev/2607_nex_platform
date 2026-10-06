# Slice 1375: AE Trace Projection

## Goal

Expose AE upload, generated-response, artifact, and render lifecycle stages to
AG through an AG-only, metadata-safe service API.

## Implementation

- Added an AE internal operations route at
  `/internal/v1/operations/traces/{trace_id}`.
- Required `service:call`, `operations:read`, ADMIN admission, and the
  `nex-ag` caller identity.
- Projected existing `ae_upload_handoffs`, `ae_chat_interactions`,
  `ae_artifacts`, and `ae_artifact_render_jobs` records without introducing a
  new domain table.
- Added compact trace indexes for upload, chat response, and artifact lookup.
- Replaced raw tenant/user identity with a SHA-256 owner digest and excluded
  messages, generated content, titles, storage references, files, and private
  artifact payloads.
- Deferred actual PostgreSQL execution to the protected S138 smoke in Slice
  1380; no remote model provider is required for this projection.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-ae-api \
  --test tests/test_nex_runtime_cross_service_trace.py \
  --test tests/test_nex_ae_trace_projection.py \
  --test tests/test_ae_trace_projection_contract.py \
  --coverage-target scripts/smoke/run_ae_trace_projection_contract.py \
  --smoke scripts/smoke/run_ae_trace_projection_contract.py
```

Expected evidence:

- authorized AG reads succeed while missing scope and non-AG callers fail;
- AE trace tests cover memory, SQLite, redaction, all lifecycle mappings, and
  fail-closed database errors;
- contract validation reports `166` schemas, `226` examples, `194` negative
  examples, and `7` OpenAPI documents;
- evidence reports `checks=11/11`, `stages=4`, and `next=1376`.

Observed evidence:

- Slice Gate (`nex-ae-api`): `2,934 passed`, `5` protected PostgreSQL tests
  skipped by explicit opt-in policy.
- Repository statement coverage: `98.33%`.
- Repository branch coverage: `96.22%`.
- AE trace projection and evidence runner focused statement/branch coverage:
  `100%`/`100%`.
- Contract validation: `166` schemas, `226` examples, `194` negative
  examples, and `7` OpenAPI documents.
- Evidence: `checks=11/11`, `stages=4`, `digests=4`, `next=1376`.
- SQLite exercised the SQLAlchemy adapter; actual PostgreSQL remains deferred
  to Slice 1380. No remote provider was contacted.
