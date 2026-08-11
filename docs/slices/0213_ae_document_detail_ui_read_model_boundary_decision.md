# Slice 0213: AE Document Detail UI/Read-Model Boundary Decision

## Scope

Slice 0213 freezes the first AE document detail UI/read-model boundary after
Slices 0211 and 0212 added the AE facade and public contract.

Implemented:

- Updated the service boundary decision record with the AE document detail UI
  path.
- Updated the AE service README with the current read-model position.
- Added an AE document detail projection edge-case regression for missing CX
  detail status text.

## Decision

Near-term AE document detail UI should use this path:

```text
nex-ae-web -> nex-ae-api GET /api/v1/documents/{document_id}
           -> nex-cx GET /api/v1/documents/{document_id}?tenant_id=...&owner_user_id=...
```

Do not add an AE-local document detail table in the current workstream.

`nex-cx` remains the authority for document detail/read-model data: source
lineage, extraction, summaries, summary embeddings, chunks, retrieval, and
processing metadata. `nex-ae-api` owns upload handoff, workspace, chat/activity,
and artifact-facing state.

## Revisit Criteria

An AE-local document detail read model can be reconsidered if UI latency,
offline/history snapshots, cross-document AE-only aggregation, or AG debugging
needs require an AE-owned materialized view.

If added later, that read model must store only safe hashes, refs, statuses,
small previews, and freshness metadata. It must not store source bytes,
markdown text, raw summaries, embedding vectors, storage keys, storage URIs, or
local filesystem paths.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_documents.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
27 passed, 1 warning
```

Observed full quality gate:

```text
1617 passed, 1 warning
statement_coverage=97.96%
branch_coverage=93.70%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
cx_document_detail_postgres_smoke=skipped reason=NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE
```
