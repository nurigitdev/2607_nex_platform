# Slice 0957: CX Document Intelligence Orchestration and API

## Goal

Compose summary generation, durable private summary storage, summary embedding,
pgvector publication, and owner-scoped summary similarity behind one protected
CX document-intelligence boundary.

## Implementation

- Adds `POST /api/v1/documents/{document_id}/intelligence/run` to execute the
  generation, embedding, metadata persistence, private vector publication, and
  freshness verification sequence.
- Adds `POST /api/v1/documents/{document_id}/intelligence/similar` to reuse the
  persisted current summary vector as the query, exclude the source document,
  and return only owner-scoped safe candidate metadata.
- Requires exact tenant and owner authorization before any provider or storage
  work and keeps cross-owner resources indistinguishable from missing ones.
- Returns bounded summary preview and provider/hash/freshness lineage, but never
  raw summary text or raw vectors.
- Enables durable private summary text, summary pgvector, and summary similarity
  dependencies only in PostgreSQL runtime mode. Memory regression mode remains
  deterministic and fail-closed for the integrated persistence API.
- Wires the summary route to the NeX-MO generation client and shares the
  configured NeX-MO embedding client and alias with the integrated workflow.
- Documents both new routes in NeX-CX OpenAPI `0.96.0`; response schema and
  metadata-only operational event hardening remain assigned to Slice 0958.

Actual PostgreSQL migration and remote generation/embedding execution remain
assigned to the protected Slice 0959 smoke.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_document_intelligence_orchestration.py \
  tests/test_cx_document_intelligence_orchestration.py \
  --cov=nex_cx.document_intelligence_orchestration \
  --cov=run_cx_document_intelligence_orchestration \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_document_intelligence_orchestration.py --summary
```

Observed on 2026-09-22:

- Focused orchestration and API suite: `15 passed`; orchestration and evidence
  modules reached `100%` statement and branch coverage.
- Existing document-intelligence contract plus orchestration regression:
  `41 passed`.
- Deterministic orchestration evidence: `10/10` checks passed with one
  owner-scoped similarity candidate.
- Full regression: `7300 passed`.
- Full coverage: statement `98.89%`, branch `96.59%`.
- Contract validation: `85` schemas, `136` positive examples, `101` negative
  examples, and `7` OpenAPI documents passed.
